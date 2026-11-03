/**
 * fetch の薄い包み。Cookie を送り、JSON を受け取る。
 * 失敗はサーバーの {"error": "<code>"} の code と HTTP status を持つ ApiError にする。
 */

/** 通信そのものができなかった（status は 0）。 */
export const NETWORK_ERROR = "network_error";
/** 失敗の本文に error コードが無かった。 */
export const UNKNOWN_ERROR = "unknown_error";
/** 成功の本文が JSON として読めなかった。 */
export const INVALID_RESPONSE = "invalid_response";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string) {
    super(`API error ${status}: ${code}`);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }

  get isUnauthorized(): boolean {
    return this.status === 401;
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}

type Method = "GET" | "POST";

function buildInit(method: Method, body: unknown): RequestInit {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body === undefined) {
    return { method, headers, credentials: "include" };
  }
  return {
    method,
    headers: { ...headers, "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(body),
  };
}

async function readErrorCode(res: Response): Promise<string> {
  try {
    const data: unknown = await res.json();
    if (data !== null && typeof data === "object" && "error" in data) {
      const code = (data as { error: unknown }).error;
      if (typeof code === "string" && code.length > 0) {
        return code;
      }
    }
  } catch {
    // 本文が JSON でない（プロキシのエラーページ等）
  }
  return UNKNOWN_ERROR;
}

export async function request<T>(
  method: Method,
  path: string,
  body?: unknown,
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, buildInit(method, body));
  } catch {
    throw new ApiError(0, NETWORK_ERROR);
  }
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorCode(res));
  }
  if (res.status === 204) {
    return undefined as T;
  }
  try {
    return (await res.json()) as T;
  } catch {
    throw new ApiError(res.status, INVALID_RESPONSE);
  }
}

export function getJson<T>(path: string): Promise<T> {
  return request<T>("GET", path);
}

export function postJson<T>(path: string, body?: unknown): Promise<T> {
  return request<T>("POST", path, body);
}

/** 経路の一部に入れる値を URL エンコードする。 */
export function seg(value: string | number): string {
  return encodeURIComponent(String(value));
}
