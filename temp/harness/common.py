"""Shared settings for the pokechamp harness scripts.

This harness is DeepSeek-only and plays singles battles.
"""

import random

import numpy as np

# Prompt algorithms implemented by pokechamp.LLMPlayer.choose_move
prompt_algos = [
    "io",
    "sc",
    "tot",
    "minimax",
]

# Agents that get_llm_player can build: the LLM agent plus poke-env baselines
bot_choices = ['pokechamp', 'deepseek', 'one_step', 'abyssal', 'max_power', 'random']

# Suffix appended to account names so parallel runs do not collide
PNUMBER1 = str(np.random.randint(0, 10000))
print(PNUMBER1)

seed = 100
random.seed(seed)
np.random.seed(seed)
