import { config } from "./config";
import { runLoginFlow } from "./auth/login-server";
import { deleteCredentials, loadCredentials } from "./auth/token-store";
import { buildApp } from "./server/app";

const COMMANDS = ["serve", "login", "logout", "status", "help"] as const;
type Command = (typeof COMMANDS)[number];

async function main(): Promise<void> {
  const command = parseCommand(process.argv[2]);

  switch (command) {
    case "login":
      return runLogin();
    case "logout":
      return runLogout();
    case "status":
      return runStatus();
    case "help":
      return printHelp();
    case "serve":
    default:
      return runServer();
  }
}

function parseCommand(arg: string | undefined): Command {
  if (!arg) return "serve";
  if ((COMMANDS as readonly string[]).includes(arg)) return arg as Command;
  console.error(`Unknown command: ${arg}`);
  console.error("");
  printHelp();
  process.exit(1);
}

async function runLogin(): Promise<void> {
  console.log("Iniciando fluxo de login OAuth...");
  const credentials = await runLoginFlow();
  console.log(`\nLogin conclu\u00eddo. Account ID: ${mask(credentials.accountId)}`);
  console.log(`Token expira em: ${formatExpiry(credentials.expiresAt)}`);
}

async function runLogout(): Promise<void> {
  await deleteCredentials();
  console.log("Credenciais removidas.");
}

async function runStatus(): Promise<void> {
  const loaded = await loadCredentials();
  if (!loaded) {
    console.log("Nenhuma credencial encontrada. Execute 'login'.");
    return;
  }
  const { credentials, source } = loaded;
  console.log(`Origem: ${source}`);
  console.log(`Account ID: ${mask(credentials.accountId)}`);
  console.log(`Expira em: ${formatExpiry(credentials.expiresAt)}`);
  console.log(`Estado: ${isExpired(credentials.expiresAt) ? "expirado" : "válido"}`);
}

async function runServer(): Promise<void> {
  const app = buildApp();
  console.log(`Proxy OpenAI <- ChatGPT Plan escutando em http://localhost:${config.port}`);
  Bun.serve({ port: config.port, fetch: app.fetch });
}

function printHelp(): void {
  console.log(`chatgpt-openai-proxy

Comandos:
  serve    Inicia o servidor proxy (default)
  login    Executa o fluxo OAuth no navegador
  logout   Remove as credenciais salvas
  status   Mostra o estado atual das credenciais
  help     Exibe esta ajuda

Vari\u00e1veis de ambiente:
  PORT                  Porta do servidor (default 3000)
  OAUTH_CALLBACK_PORT   Porta do callback OAuth (default 1455)
  CHATGPT_PROXY_HOME    Diret\u00f3rio base das credenciais
  CHATGPT_ACCESS_TOKEN  Token via env (Docker headless)
  CHATGPT_REFRESH_TOKEN Token via env (Docker headless)
  CHATGPT_ACCOUNT_ID    Account id via env (Docker headless)
  CHATGPT_EXPIRES_AT    Expira\u00e7\u00e3o (ms) via env (Docker headless)`);
}

function mask(accountId: string): string {
  if (accountId.length <= 8) return accountId;
  return `${accountId.slice(0, 4)}...${accountId.slice(-4)}`;
}

function formatExpiry(expiresAt: number): string {
  return new Date(expiresAt).toISOString();
}

function isExpired(expiresAt: number): boolean {
  return expiresAt <= Date.now();
}

main().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
