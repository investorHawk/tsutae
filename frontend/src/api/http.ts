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

export interface RequestOptions {
  /**
   * この時間（ms）で打ち切る（AbortController）。打ち切りは通信の失敗と同じ
   * ApiError(0, network_error)。省略すると打ち切らない。本文の読み込みまで含む。
   */
  timeoutMs?: number;
}

function buildInit(
  method: Method,
  body: unknown,
  signal: AbortSignal | undefined,
): RequestInit {
  const headers: Record<string, string> = { Accept: "application/json" };
  const base: RequestInit = { method, credentials: "include", signal };
  if (body === undefined) {
    return { ...base, headers };
  }
  return {
    ...base,
    headers: { ...headers, "Content-Type": "application/json" },
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

async function readBody<T>(
  res: Response,
  signal: AbortSignal | undefined,
): Promise<T> {
  if (!res.ok) {
    const code = await readErrorCode(res);
    throw signal?.aborted
      ? new ApiError(0, NETWORK_ERROR)
      : new ApiError(res.status, code);
  }
  if (res.status === 204) {
    return undefined as T;
  }
  try {
    return (await res.json()) as T;
  } catch {
    // 打ち切りで本文が途切れたのは通信の失敗（形の不正ではない）
    throw new ApiError(
      signal?.aborted ? 0 : res.status,
      signal?.aborted ? NETWORK_ERROR : INVALID_RESPONSE,
    );
  }
}

export async function request<T>(
  method: Method,
  path: string,
  body?: unknown,
  options: RequestOptions = {},
): Promise<T> {
  const { timeoutMs } = options;
  const controller = timeoutMs === undefined ? null : new AbortController();
  const timer =
    controller === null
      ? undefined
      : setTimeout(() => controller.abort(), timeoutMs);
  const signal = controller?.signal;
  try {
    let res: Response;
    try {
      res = await fetch(path, buildInit(method, body, signal));
    } catch {
      throw new ApiError(0, NETWORK_ERROR);
    }
    return await readBody<T>(res, signal);
  } finally {
    if (timer !== undefined) {
      clearTimeout(timer);
    }
  }
}

export function getJson<T>(path: string, options?: RequestOptions): Promise<T> {
  return request<T>("GET", path, undefined, options);
}

export function postJson<T>(
  path: string,
  body?: unknown,
  options?: RequestOptions,
): Promise<T> {
  return request<T>("POST", path, body, options);
}

/** 経路の一部に入れる値を URL エンコードする。 */
export function seg(value: string | number): string {
  return encodeURIComponent(String(value));
}
