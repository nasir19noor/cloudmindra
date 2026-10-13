// Portal shell (DESIGN.md §11): signs the user in, resolves the workspace from the URL,
// renders the top bar and the module sidebar, and hands the page its context.
// Pages call `const ctx = await bootPortal()` from their own <script>.
import { $, createApi, errorText, esc, showMsg, ROLE_LABEL, canManageWorkspace, type Role } from './portal';

export type Workspace = { id: string; name: string; role: Role; currency: string };
export type Module = {
  key: string; name: string; available: boolean; tier: 'free' | 'pro'; pro_until: string | null;
  limits: Record<string, number>; usage: Record<string, number>; features: string[]; labels: Record<string, string>;
};
export type User = { sub: string; email: string; name: string; provider: string; is_admin: boolean; last_org_id: string | null };
export type PortalContext = {
  api: ReturnType<typeof createApi>;
  user: User;
  workspace: Workspace & { member_count: number };
  workspaces: Workspace[];
  modules: Module[];
  canManage: boolean;
  orgPath: (section?: string) => string;
  orgApi: (path?: string) => string;
};

// Sections that exist for every workspace; anything else falls back to the overview when switching
const COMMON_SECTIONS = ['', 'uptime', 'alerts', 'review', 'cost', 'security', 'iac'];

function view(name: 'loading' | 'missing' | 'app') {
  for (const v of ['loading', 'missing', 'app']) $(`shell-${v}`).classList.toggle('hidden', v !== name);
}

function navItem(href: string, label: string, active: boolean, extra = '') {
  return `<a href="${esc(href)}" class="flex items-center justify-between gap-2 rounded-xl px-3 py-2 text-body transition-colors ${
    active ? 'bg-fg/[0.07] font-medium text-fg' : 'text-fg/70 hover:bg-fg/[0.04] hover:text-fg'
  }" ${active ? 'aria-current="page"' : ''}><span class="truncate">${esc(label)}</span>${extra}</a>`;
}

function renderSidebar(ctx: PortalContext, section: string) {
  const badge = (m: Module) =>
    !m.available
      ? '<span class="text-[10px] uppercase tracking-[0.1em] text-fg/40">Soon</span>'
      : m.tier === 'pro'
        ? '<span class="rounded-full bg-brand/15 px-1.5 text-[10px] font-medium uppercase tracking-[0.1em] text-brand">Pro</span>'
        : '<span class="rounded-full bg-fg/[0.06] px-1.5 text-[10px] font-medium uppercase tracking-[0.1em] text-fg/55">Free</span>';
  const modules = ctx.modules
    .map((m) => navItem(ctx.orgPath(m.key), m.name, section === m.key, badge(m)))
    .join('');
  $('shell-nav').innerHTML = `
    ${navItem(ctx.orgPath(), 'Overview', section === '')}
    <p class="eyebrow mb-1 mt-4 px-3">Modules</p>
    ${modules}
    <p class="eyebrow mb-1 mt-4 px-3">Workspace</p>
    ${navItem(ctx.orgPath('alerts'), 'Email alerts', section === 'alerts')}
    ${ctx.canManage ? navItem(ctx.orgPath('settings'), 'Settings & team', section === 'settings') : ''}`;
}

export async function bootPortal(): Promise<PortalContext> {
  const shell = $('portal-shell');
  const api = createApi(shell.dataset.api as string);
  const orgId = shell.dataset.org as string;
  const section = shell.dataset.section ?? '';

  const meRes = await api('/api/auth/me').catch(() => null);
  if (!meRes?.ok) {
    location.href = '/portal';
    throw new Error('signed out');
  }
  const user: User = await meRes.json();
  const listRes = await api('/api/orgs');
  const list = await listRes.json();
  const workspaces: Workspace[] = list.workspaces;

  $('shell-user').textContent = user.email;
  $('shell-admin').classList.toggle('hidden', !user.is_admin);

  if (!workspaces.some((w) => w.id === orgId)) {
    view('missing');
    throw new Error('workspace not found');
  }
  const detail = await (await api(`/api/orgs/${encodeURIComponent(orgId)}`)).json();
  const { modules, ...workspace } = detail;
  const ctx: PortalContext = {
    api,
    user,
    workspace,
    workspaces,
    modules,
    canManage: canManageWorkspace(workspace.role),
    orgPath: (s = '') => `/portal/${encodeURIComponent(orgId)}${s ? `/${s}` : ''}`,
    orgApi: (p = '') => `/api/orgs/${encodeURIComponent(orgId)}${p}`,
  };

  // Top bar: workspace switcher, role, new workspace / leave
  const select = $<HTMLSelectElement>('shell-ws');
  select.innerHTML = workspaces.map((w) => `<option value="${esc(w.id)}">${esc(w.name)}</option>`).join('');
  select.value = orgId;
  $('shell-role').textContent = ROLE_LABEL[workspace.role];
  $('shell-leave').classList.toggle('hidden', ctx.canManage);
  renderSidebar(ctx, section);

  select.addEventListener('change', () => {
    const target = COMMON_SECTIONS.includes(section) ? section : '';
    location.href = `/portal/${encodeURIComponent(select.value)}${target ? `/${target}` : ''}`;
  });
  $('shell-new').addEventListener('click', async () => {
    const name = prompt('Name of the new workspace, e.g. your company or project')?.trim();
    if (!name) return;
    const res = await api('/api/orgs', { method: 'POST', body: JSON.stringify({ name }) }).catch(() => null);
    if (!res?.ok) return showMsg('shell-error', await errorText(res, 'Could not create the workspace'));
    location.href = `/portal/${encodeURIComponent((await res.json()).id)}`;
  });
  $('shell-leave').addEventListener('click', async () => {
    if (!confirm(`Leave ${workspace.name}? You will lose access to its data.`)) return;
    const res = await api(ctx.orgApi(`/members/${encodeURIComponent(user.sub)}`), { method: 'DELETE' }).catch(() => null);
    if (!res?.ok) return showMsg('shell-error', await errorText(res, 'Could not leave the workspace'));
    location.href = '/portal';
  });

  // Remember this workspace for the next visit to /portal
  if (list.last_org_id !== orgId) api(ctx.orgApi('/select'), { method: 'POST' }).catch(() => {});

  document.title = `${document.title.split(' | ')[0]} · ${workspace.name} | CloudMindra`;
  view('app');
  return ctx;
}
