"""DeepSeek backend for the LLM player.

The DeepSeek API is OpenAI-compatible, so a single client with a custom
``base_url`` is enough. This module wraps the chat completion call, returns raw
model text, and appends a decision trace to ``llm_trace.log`` next to the harness
scripts - the same idea as ``_log()`` in the repository root's
``deepseek_flash_player.py``.
"""

import datetime
import os
from pathlib import Path
from time import sleep, time

from openai import OpenAI, RateLimitError

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"

# Trace log lives in the harness root (temp/harness/llm_trace.log) and does not
# depend on the working directory. HARNESS_TRACE_LOG overrides the path, and
# HARNESS_TRACE_LOG=0 turns tracing off.
TRACE_LOG_PATH = Path(__file__).resolve().parents[1] / "llm_trace.log"
TRACE_LOG_MAX_CHARS = 8000
# Thinking tokens are billed against max_tokens, so small answer budgets are
# raised to this floor. max_tokens is only a ceiling, so the floor costs nothing
# unless the model really reasons that long; measured turns needed 5000-7000
# tokens, so 2048 (and then 4096) kept truncating the answer. The API accepted
# ceilings up to 32768.
THINKING_MIN_TOKENS = 8192


class DeepSeekPlayer():
    """Minimal DeepSeek chat completion client used by ``LLMPlayer``."""

    def __init__(self, api_key=""):
        # The key is never logged or stored anywhere else: DEEPSEEK_API_KEY
        # from the environment (usually loaded from .env) is the single source.
        self.api_key = api_key or os.getenv('DEEPSEEK_API_KEY', '')
        self.base_url = os.getenv('DEEPSEEK_BASE_URL', DEEPSEEK_BASE_URL)
        # Thinking mode lets the model reason before answering. Set
        # DEEPSEEK_THINKING=0 to disable it and only get the final answer, and
        # DEEPSEEK_REASONING_EFFORT=low|medium|high to control how long it reasons.
        self.thinking = os.getenv('DEEPSEEK_THINKING', '1').lower() not in ('0', 'false', 'no')
        self.reasoning_effort = os.getenv('DEEPSEEK_REASONING_EFFORT', 'high').lower()
        if self.reasoning_effort not in ('low', 'medium', 'high'):
            self.reasoning_effort = 'high'
        self.completion_tokens = 0
        self.prompt_tokens = 0
        self.last_reasoning = ""
        self.call_count = 0
        self.trace_log = self._resolve_trace_log()

    @staticmethod
    def _resolve_trace_log():
        """Return the file to append the trace to, or None when disabled."""
        setting = os.getenv('HARNESS_TRACE_LOG')
        if setting is None:
            return TRACE_LOG_PATH
        if setting.strip().lower() in ('', '0', 'false', 'no', 'off'):
            return None
        return Path(setting).expanduser()

    def _log(self, message: str) -> None:
        """Append one entry to the trace log (never let logging break a battle)."""
        if self.trace_log is None:
            return
        try:
            with open(self.trace_log, 'a', encoding='utf-8') as trace:
                trace.write(message + '\n')
        except OSError as e:
            print(f'could not write trace log {self.trace_log}: {e}')

    @staticmethod
    def _clip(text) -> str:
        """Cap one field so a very long reasoning block cannot explode the log."""
        text = '' if text is None else str(text)
        if len(text) > TRACE_LOG_MAX_CHARS:
            return f"{text[:TRACE_LOG_MAX_CHARS]}...[truncated, {len(text)} chars total]"
        return text

    def _log_request(self, kind, model, json_format, budget, prompt_chars, battle, ps_client):
        self.call_count += 1
        agent = getattr(getattr(ps_client, 'account_configuration', None), 'username', '')
        if battle is not None:
            where = f"battle={getattr(battle, 'battle_tag', '-')} turn={getattr(battle, 'turn', '-')}"
        else:
            where = "battle=-"
        self._log(
            f"--- call #{self.call_count} {datetime.datetime.now():%Y-%m-%d %H:%M:%S}"
            f" | {kind} | agent={agent} | {where}"
            f" | model={model or DEFAULT_MODEL} | json={bool(json_format)}"
            f" | thinking={self.reasoning_effort if self.thinking else 'off'}"
            f" | max_tokens={budget} | prompt_chars={prompt_chars}"
        )

    def _log_response(self, response, message, reasoning, started, finish_reason):
        self._log(f"ANSWER: {self._clip(message)}")
        if reasoning:
            self._log(f"THINKING: {self._clip(reasoning)}")
        usage = response.usage
        tokens = (f"prompt_tokens={usage.prompt_tokens} completion_tokens={usage.completion_tokens} "
                  if usage else "")
        self._log(f"USAGE: {tokens}finish={finish_reason} latency={time() - started:.1f}s")

    def _create(self, **kwargs):
        """Send one chat completion request, retrying once after a rate limit."""
        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        try:
            return client.chat.completions.create(**kwargs)
        except RateLimitError:
            print('deepseek rate limit error, retrying in 5s')
            sleep(5)
            return self._create(**kwargs)

    def _think_kwargs(self):
        # How much the model may reason before answering; lower effort means
        # shorter (cheaper, faster) thinking and fewer truncated answers.
        return {'reasoning_effort': self.reasoning_effort,
                'extra_body': {'thinking': {'type': 'enabled'}}}

    def _budget(self, max_tokens, factor=1):
        # Thinking tokens are billed against max_tokens, so the caller's small
        # answer budgets (100-200 tokens) are raised to leave room for them.
        if not self.thinking:
            return max_tokens
        return max(max_tokens, THINKING_MIN_TOKENS) * factor

    def _request(self, system_prompt, user_prompt, model, temperature, stop, max_tokens, json_output, factor=1):
        kwargs = dict(
            model=model or DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=temperature,
            stream=False,
            stop=stop or None,
            max_tokens=self._budget(max_tokens, factor),
        )
        if json_output:
            kwargs['response_format'] = {"type": "json_object"}
        if self.thinking:
            kwargs.update(self._think_kwargs())
        return self._create(**kwargs)

    def _record_usage(self, response):
        if response.usage:
            self.completion_tokens += response.usage.completion_tokens
            self.prompt_tokens += response.usage.prompt_tokens

    def _call(self, kind, system_prompt, user_prompt, model, temperature, stop, max_tokens,
              battle=None, ps_client=None, json_format=False, json_output=False) -> tuple:
        """Traced API call: log the request, run it, log answer and usage.

        A thinking model occasionally spends the whole budget on reasoning and
        returns an empty answer (finish_reason="length"), which the prompt
        algorithms cannot parse; that case is repeated once with double budget.
        """
        prompt_chars = len(system_prompt or '') + len(user_prompt or '')
        for factor in (1, 2):
            started = time()
            self._log_request(kind, model, json_format, self._budget(max_tokens, factor),
                              prompt_chars, battle, ps_client)
            try:
                response = self._request(system_prompt, user_prompt, model, temperature,
                                         stop, max_tokens, json_output, factor)
            except Exception as e:
                # The caller retries; the trace keeps the reason for the failure.
                self._log(f"ERROR: {type(e).__name__}: {e}")
                raise
            choice = response.choices[0]
            message = choice.message
            reasoning = getattr(message, 'reasoning_content', None) or ''
            self.last_reasoning = reasoning
            self._record_usage(response)
            self._log_response(response, message.content, reasoning, started, choice.finish_reason)
            if message.content or choice.finish_reason != 'length':
                return message.content, reasoning
            self._log(f"RETRY: empty answer with finish=length, retrying with "
                      f"max_tokens={self._budget(max_tokens, 2)}")
        # Both attempts came back empty: hand the empty answer back instead of None,
        # the prompt algorithms have their own retry and fallback handling.
        return '', self.last_reasoning

    def get_LLM_action(self, system_prompt, user_prompt, model=DEFAULT_MODEL, temperature=0.7, json_format=False, seed=None, stop=[], max_tokens=200, actions=None, battle=None, ps_client=None) -> str:
        outputs, reasoning = self._call(
            'action', system_prompt, user_prompt, model, temperature, stop, max_tokens,
            battle=battle, ps_client=ps_client, json_format=json_format, json_output=json_format,
        )
        # (processed output, json flag, raw text shown in the battle chat)
        return outputs, bool(json_format), reasoning or outputs

    def get_LLM_query(self, system_prompt, user_prompt, temperature=0.7, model=DEFAULT_MODEL, json_format=False, seed=None, stop=[], max_tokens=200, battle=None, ps_client=None):
        """Free-form query used by LocalSim when building the strategy prompt.

        Unlike an action request this never asks the API for a JSON object: the
        caller only pads the prompt and parses the answer itself.
        """
        output_padding = '\n{"' if json_format else ''
        message, _ = self._call(
            'query', system_prompt, user_prompt + output_padding, model, temperature, stop, max_tokens,
            battle=battle, ps_client=ps_client, json_format=json_format, json_output=False,
        )
        message = message or ''
        if json_format:
            json_end = message.find('}') + 1
            if json_end > 0:
                return '{"' + message[:json_end], True
        return message, False
