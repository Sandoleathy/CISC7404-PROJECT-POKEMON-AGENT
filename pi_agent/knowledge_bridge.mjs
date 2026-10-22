// Persistent JSON-lines host for the pi-knowledge extension.
//
// pi-knowledge is a Node/Pi extension, not a Python package.  The Python side
// starts this process once, sends {"id", "action", "params"} lines and receives
// one {"id", "ok", "text"} line per request.  Only protocol JSON goes to stdout;
// anything the extension prints is redirected to stderr so it cannot corrupt the
// stream.

import readline from "node:readline";
import os from "node:os";
import path from "node:path";
import { existsSync } from "node:fs";
import { pathToFileURL } from "node:url";

const send = (payload) => {
	process.stdout.write(`${JSON.stringify(payload)}\n`);
};

// Keep stdout clean: the extension and native model workers may log to console.
console.log = (...args) => console.error(...args);
console.info = (...args) => console.error(...args);

function bridgeExit(message) {
	console.error(`[pi-agent knowledge bridge] ${message}`);
	send({ ready: false, error: message });
	process.exit(1);
}

function findExtension() {
	const candidates = [];
	if (process.env.PI_KNOWLEDGE_PACKAGE) {
		candidates.push(process.env.PI_KNOWLEDGE_PACKAGE);
	}
	candidates.push(
		path.join(os.homedir(), ".pi", "agent", "npm", "node_modules", "pi-knowledge", "extension.js"),
	);
	// Some global/local installs expose the built entry directly.
	candidates.push(
		path.join(os.homedir(), ".pi", "agent", "npm", "node_modules", "pi-knowledge", "dist", "index.js"),
	);
	for (const candidate of candidates) {
		if (candidate && existsSync(candidate)) {
			return candidate;
		}
	}
	bridgeExit(
		`pi-knowledge extension not found. Set PI_KNOWLEDGE_PACKAGE to its extension.js. Tried: ${candidates.join(", ")}`,
	);
}

const extensionPath = findExtension();
let extension;
try {
	extension = (await import(pathToFileURL(extensionPath).href)).default;
} catch (error) {
	bridgeExit(`could not import pi-knowledge from ${extensionPath}: ${error?.stack ?? error}`);
}
if (typeof extension !== "function") {
	bridgeExit(`pi-knowledge entry ${extensionPath} did not export an extension factory`);
}

const tools = new Map();
const pi = {
	on() {
		// The ladder agent does not need Pi lifecycle hooks.
	},
	registerTool(definition) {
		tools.set(definition.name, definition);
	},
};

try {
	await extension(pi);
} catch (error) {
	bridgeExit(`pi-knowledge extension failed to initialize: ${error?.stack ?? error}`);
}

if (!tools.has("knowledge_search")) {
	bridgeExit("pi-knowledge did not register knowledge_search");
}

send({ ready: true, tools: [...tools.keys()], extension: extensionPath });

const TOOL_FOR_ACTION = {
	search: "knowledge_search",
	show: "knowledge_show",
	status: "knowledge_status",
	doctor: "knowledge_doctor",
	symbol_search: "knowledge_symbol_search",
};

async function runAction(action, params) {
	const toolName = TOOL_FOR_ACTION[action];
	if (!toolName) {
		throw new Error(`unsupported knowledge action: ${action}`);
	}
	const tool = tools.get(toolName);
	if (!tool) {
		throw new Error(`pi-knowledge tool ${toolName} is not registered`);
	}
	const result = await tool.execute(String(Date.now()), params ?? {}, undefined, undefined, {});
	const text = (result?.content ?? [])
		.filter((item) => item?.type === "text")
		.map((item) => item.text)
		.join("\n");
	return { text, isError: result?.isError === true };
}

const reader = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
let closed = false;

for await (const line of reader) {
	const raw = line.trim();
	if (!raw) {
		continue;
	}
	let request;
	try {
		request = JSON.parse(raw);
	} catch (error) {
		console.error(`[pi-agent knowledge bridge] invalid request JSON: ${error}`);
		continue;
	}
	const id = request?.id ?? "?";
	const action = request?.action;
	if (action === "close") {
		closed = true;
		send({ id, ok: true, text: "" });
		break;
	}
	try {
		const { text, isError } = await runAction(action, request?.params ?? {});
		send({ id, ok: !isError, text, is_error: isError });
	} catch (error) {
		send({ id, ok: false, error: String(error?.stack ?? error) });
	}
}

if (!closed) {
	// stdin ended; let the process exit naturally.
}
process.exit(0);
