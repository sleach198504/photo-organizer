// Thin fetch wrapper. Errors carry the server's plain-language `detail` so views can
// show it verbatim instead of "Request failed with status 400".

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(method, url, body) {
  let response;
  try {
    response = await fetch(url, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError("Lost contact with Photo Organizer. If the window just opened, wait a moment and try again.", 0);
  }
  if (!response.ok) {
    let message = `Something went wrong (${response.status}).`;
    try {
      const data = await response.json();
      if (typeof data.detail === "string") message = data.detail;
    } catch {
      /* body wasn't JSON */
    }
    throw new ApiError(message, response.status);
  }
  return response.status === 204 ? null : response.json();
}

export const api = {
  get: (url) => request("GET", url),
  post: (url, body = {}) => request("POST", url, body),
  put: (url, body) => request("PUT", url, body),
};

export function query(params) {
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "" || value === false) continue;
    q.set(key, String(value));
  }
  const text = q.toString();
  return text ? `?${text}` : "";
}

// Media URLs. `v` is the file's mtime, so a cached thumbnail is reused until the file changes.
export const media = {
  thumb: (item) => `/media/thumb/${item.id}?v=${item.v ?? 0}`,
  preview: (item) => `/media/preview/${item.id}?v=${item.v ?? 0}`,
  original: (item) => `/media/original/${item.id}?v=${item.v ?? 0}`,
  video: (item) => `/media/video/${item.id}`,
};
