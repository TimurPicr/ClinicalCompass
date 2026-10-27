export function csrfToken() {
  return decodeURIComponent(
    document.cookie
      .split("; ")
      .find((value) => value.startsWith("cc_csrf="))
      ?.split("=")
      .slice(1)
      .join("=") || "",
  );
}
export async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const method = options.method || "GET";
  if (!["GET", "HEAD", "OPTIONS"].includes(method) && !csrfToken())
    await fetch("/api/auth/csrf", { credentials: "include" });
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  if (!["GET", "HEAD", "OPTIONS"].includes(method))
    headers.set("X-CSRF-Token", csrfToken());
  let response;
  try {
    response = await fetch(`/api${path}`, {
      ...options,
      method,
      headers,
      credentials: "include",
      body:
        options.body instanceof FormData
          ? options.body
          : options.body
            ? JSON.stringify(options.body)
            : undefined,
    });
  } catch {
    throw new Error("Не удалось связаться с сервером. Проверьте подключение.");
  }
  if (!response.ok) {
    let error;
    try {
      error = await response.json();
    } catch {
      error = { detail: `Ошибка сервера (${response.status})` };
    }
    const detail = error.detail;
    throw new Error(
      Array.isArray(detail)
        ? detail
            .map(
              (item) =>
                `${item.loc?.slice(1).join(".") || "Поле"}: ${item.msg}`,
            )
            .join("; ")
        : typeof detail === "string"
          ? detail
          : `Ошибка запроса (${response.status})`,
    );
  }
  if (response.status === 204) return null;
  return response.json();
}
