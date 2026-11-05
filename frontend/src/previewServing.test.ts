// @vitest-environment node
/**
 * Funnel に出す `vite preview` の決まり（docs/decisions.md）。
 * ポートは開かない: listen を止め、preview の middleware を直接呼ぶ。読むのは合成のファイルだけ。
 * Vite を上げてこの決まりが変わったら落ちるように、実物の preview で確かめる。
 */
import { afterAll, beforeAll, describe, expect, it } from "vitest";

const SECRET = "SYNTHETIC-OUTSIDE-OF-DIST";
const INDEX = '<div id="root"></div>';

type Next = () => void;

interface FakeRes {
  statusCode: number;
  body: string;
}

let call: (url: string) => Promise<FakeRes>;
let apiProxy: { target?: string; changeOrigin?: boolean } | undefined;
let finish: () => void = () => undefined;
let site = "";

/** node の型を tsconfig に入れないので、使う分だけ書く（sw.test.ts と同じ）。 */
async function nodeModule<T>(name: string): Promise<T> {
  return (await import(/* @vite-ignore */ `node:${name}`)) as T;
}

interface Fs {
  mkdtempSync(prefix: string): string;
  mkdirSync(path: string): void;
  writeFileSync(path: string, data: string): void;
  rmSync(path: string, options: { recursive: boolean; force: boolean }): void;
}

interface HttpModule {
  Server: { prototype: { listen: (...args: unknown[]) => unknown } };
  IncomingMessage: new (socket: null) => object;
  ServerResponse: new (req: object) => object;
}

beforeAll(async () => {
  const fs = await nodeModule<Fs>("fs");
  const os = await nodeModule<{ tmpdir(): string }>("os");
  const http = await nodeModule<HttpModule>("http");
  site = fs.mkdtempSync(`${os.tmpdir()}/tsutae-preview-`);
  fs.mkdirSync(`${site}/dist`);
  fs.writeFileSync(`${site}/dist/index.html`, INDEX);
  fs.writeFileSync(`${site}/dist/sw.js`, "// sw");
  fs.writeFileSync(`${site}/secret.txt`, SECRET);
  fs.writeFileSync(`${site}/secret.pem`, SECRET);
  fs.writeFileSync(`${site}/.env`, `KEY=${SECRET}`);

  const realListen = http.Server.prototype.listen;
  http.Server.prototype.listen = function (
    this: { emit(name: string): void },
    ...args: unknown[]
  ) {
    const done = args.find((a) => typeof a === "function") as Next | undefined;
    queueMicrotask(() => {
      this.emit("listening");
      done?.();
    });
    return this;
  };
  const { preview, resolveConfig } = await import("vite");
  const server = await preview({
    root: site,
    configFile: false,
    logLevel: "silent",
    preview: { host: "127.0.0.1", port: 5173, open: false },
  });
  finish = () => {
    http.Server.prototype.listen = realListen;
    fs.rmSync(site, { recursive: true, force: true });
    void server.close().catch(() => undefined);
  };
  // 本物の設定を読む（cwd は frontend）。preview の proxy は server.proxy を引き継ぐ
  const resolved = await resolveConfig(
    { logLevel: "silent" },
    "serve",
    "production",
    "production",
    true,
  );
  apiProxy = resolved.preview.proxy?.["/api"] as typeof apiProxy;
  call = (url) =>
    new Promise((resolve, reject) => {
      const req = new http.IncomingMessage(null) as Record<string, unknown> & {
        push(chunk: null): void;
      };
      Object.assign(req, {
        url,
        originalUrl: url,
        method: "GET",
        headers: { host: "evil.example", accept: "text/html,*/*" },
      });
      req.push(null);
      const res = new http.ServerResponse(req) as Record<string, unknown> & {
        statusCode: number;
      };
      const chunks: string[] = [];
      res.write = (chunk: unknown) => {
        chunks.push(String(chunk));
        return true;
      };
      res.end = (chunk?: unknown) => {
        if (chunk !== undefined && typeof chunk !== "function") {
          chunks.push(String(chunk));
        }
        resolve({ statusCode: res.statusCode, body: chunks.join("") });
        return res;
      };
      server.middlewares(req as never, res as never, () =>
        reject(new Error(`${url} はどの middleware も返さなかった`)),
      );
    });
});

afterAll(() => {
  finish();
});

describe("vite preview", () => {
  it("serves what is in dist, and index.html for the app's paths", async () => {
    expect((await call("/sw.js")).body).toContain("// sw");
    expect((await call("/today")).body).toContain(INDEX);
  });

  it.each([
    "/@fs{site}/secret.txt",
    "/@fs{site}/secret.txt?raw??",
    "/@fs{site}/secret.txt?import&raw??",
    "/@fs{site}/secret.pem?import&raw??",
    "/@fs{site}/.env?import&raw??",
    "/../secret.txt",
    "/..%2fsecret.txt",
    "/%2e%2e/secret.txt",
    "/%2e%2e%2fsecret.txt",
    "/../.env",
  ])("does not read outside of dist: %s", async (path) => {
    const { body } = await call(path.replace("{site}", site));
    expect(body).not.toContain(SECRET);
  });

  it.each(["/@vite/client", "/@id/x", "/__open-in-editor?file=x", "/src/x.ts"])(
    "has none of the dev server's paths: %s",
    async (path) => {
      expect((await call(path)).body).toContain(INDEX);
    },
  );

  it("passes /api to the backend without changing the Host", () => {
    expect(apiProxy?.target).toBe("http://127.0.0.1:8000");
    expect(apiProxy?.changeOrigin).toBe(false);
  });
});
