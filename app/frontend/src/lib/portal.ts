// Shared browser helpers for /portal pages.

export const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;

// Every customer-supplied value goes through esc() before touching innerHTML
export const esc = (v: unknown) =>
  String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);

export function createApi(base: string) {
  return (path: string, init: RequestInit = {}) =>
    fetch(`${base}${path}`, {
      credentials: 'include',
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init.headers || {}) },
    });
}

export async function errorText(res: Response | null, fallback: string) {
  if (!res) return 'Could not reach the server';
  const body = await res.json().catch(() => ({}));
  if (typeof body.detail === 'string') return body.detail;
  if (Array.isArray(body.detail)) return body.detail[0]?.msg ?? fallback;
  return fallback;
}

export type Role = 'owner' | 'admin' | 'member' | 'viewer';
export const ROLE_LABEL: Record<string, string> = { owner: 'Owner', admin: 'Admin', member: 'Member', viewer: 'Viewer' };
export const canManageWorkspace = (role: Role) => role === 'owner' || role === 'admin';
