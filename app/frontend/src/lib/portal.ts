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

export function ago(iso: string | null) {
  if (!iso) return 'never';
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

// Show a status line under a form: red for errors, green for success
export function showMsg(id: string, text: string | null, ok = false) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = text ?? '';
  el.classList.toggle('hidden', !text);
  el.classList.toggle('text-red-600', !ok);
  el.classList.toggle('text-emerald-700', ok);
}

export type AuditEvent = {
  id: number; action: string; actor: string | null; app_key?: string | null; details: Record<string, any>; created_at: string;
};

// Plain-language line for an audit action; the caller escapes the result
export function describeActivity(e: AuditEvent): string {
  const d = e.details ?? {};
  const pair = (k: string) => (Array.isArray(d[k]) ? `${d[k][0] ?? '–'} → ${d[k][1] ?? '–'}` : '');
  switch (e.action) {
    case 'org.created': return `created the workspace "${d.name}"`;
    case 'org.updated': return `changed ${Object.keys(d).map((k) => `${k} (${pair(k)})`).join(', ')}`;
    case 'org.seat_limit_changed': return `set the seat limit to ${d.to ?? 'the default'}`;
    case 'module.tier_changed': return `changed ${e.app_key ?? 'a module'} from ${d.from} to ${d.to}${d.pro_until ? ` (until ${d.pro_until.slice(0, 10)})` : ''}`;
    case 'member.invited': return `${d.resent ? 're-sent an invitation to' : 'invited'} ${d.email} as ${ROLE_LABEL[d.role] ?? d.role}`;
    case 'invitation.cancelled': return `cancelled the invitation for ${d.email}`;
    case 'member.joined': return `joined as ${ROLE_LABEL[d.role] ?? d.role}`;
    case 'member.role_changed': return `changed a member's role from ${ROLE_LABEL[d.from] ?? d.from} to ${ROLE_LABEL[d.to] ?? d.to}`;
    case 'member.removed': return `removed ${d.email}`;
    case 'member.left': return 'left the workspace';
    case 'uptime.monitor.created': return `added the monitor "${d.name}" (${d.url})`;
    case 'uptime.monitor.updated': return `updated a monitor: ${Object.keys(d).map((k) => `${k} ${pair(k)}`).join(', ')}`;
    case 'uptime.monitor.deleted': return `deleted the monitor "${d.name}"`;
    case 'notifications.updated': return 'changed their email alert settings';
    case 'job.retried': return `retried a ${d.was} ${d.type} job`;
    case 'job.cancelled': return `cancelled a ${d.type} job`;
    case 'platform.admin_granted': return `made ${d.email} a platform admin`;
    case 'platform.admin_revoked': return `removed ${d.email} as platform admin`;
    default: return e.action;
  }
}

export function renderActivity(events: AuditEvent[]): string {
  return events.length
    ? events
        .map(
          (e) => `
        <li class="flex flex-wrap items-baseline justify-between gap-3 px-4 py-3">
          <p class="min-w-0 text-body"><b class="font-medium">${esc(e.actor ?? 'CloudMindra')}</b> ${esc(describeActivity(e))}</p>
          <p class="shrink-0 text-caption text-fg/55">${esc(new Date(e.created_at).toLocaleString())}</p>
        </li>`,
        )
        .join('')
    : '<li class="px-4 py-6 text-center text-caption text-fg/50">No activity yet</li>';
}
