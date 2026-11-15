import { call } from "../api";
export const get = (path: string) => call("/api/v1" + path, {}, "tenant");
export const post = (
  path: string,
  body: unknown,
  version?: number,
  key = crypto.randomUUID(),
) =>
  call(
    "/api/v1" + path,
    {
      method: "POST",
      headers: {
        "Idempotency-Key": key,
        ...(version === undefined ? {} : { "If-Match": String(version) }),
      },
      body: JSON.stringify(body),
    },
    "tenant",
  );
export const patch = (path: string, body: unknown, version: number) =>
  call(
    "/api/v1" + path,
    {
      method: "PATCH",
      headers: { "If-Match": String(version) },
      body: JSON.stringify(body),
    },
    "tenant",
  );
export const put = (path: string, body: unknown) =>
  call(
    "/api/v1" + path,
    { method: "PUT", body: JSON.stringify(body) },
    "tenant",
  );
export const form = (event: React.FormEvent<HTMLFormElement>) => {
  event.preventDefault();
  return Object.fromEntries(new FormData(event.currentTarget));
};
