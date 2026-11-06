import {
  ArrowUp, Check, ChevronDown, ChevronRight, Download, Ellipsis, ExternalLink, FileText, Filter, Folder, FolderInput, FolderOpen, FolderPlus,
  Menu, PanelLeft, PanelRight, Pencil, Plus, Search, Square, SquarePen, ThumbsDown, ThumbsUp, Trash2, X,
} from 'lucide';
import { MorphIcon } from 'morphicons/react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { FluidAgentOrb } from './vendor/reactdrops/fluid-agent-orb';

/** 简洁标识：实心圆里一条上升折线。 */
const Logo = ({ size = 20 }) => (
  <svg className="logo" width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
    <circle cx="12" cy="12" r="12" fill="#0d0d0d" />
    <path d="M6.5 15.5 10.5 11l3 2.5 4-5" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const Icon = ({ icon, size = 16, ...rest }) => <MorphIcon icon={icon} size={size} strokeWidth={1.75} reducedMotion="user" {...rest} />;

async function api(path, options) {
  const r = await fetch(path, options);
  if (!r.ok) {
    let detail = '';
    try { detail = (await r.json()).detail; } catch { /* 非 JSON 错误 */ }
    throw new Error(detail || `请求失败（${r.status}）`);
  }
  return r.json();
}
const json = (method, body) => ({ method, headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });

// ---------- 左栏：项目 → 任务 ----------
function useFloatingMenu() {
  const [menu, setMenu] = useState(null);
  useEffect(() => {
    if (!menu) return undefined;
    const close = () => setMenu(null);
    const t = setTimeout(() => document.addEventListener('click', close));
    return () => { clearTimeout(t); document.removeEventListener('click', close); };
  }, [menu]);
  return [menu, setMenu];
}

function InlineEdit({ value, label, onSave, onCancel }) {
  const [text, setText] = useState(value);
  const done = useRef(false);
  const commit = () => { if (!done.current) { done.current = true; onSave(text); } };
  return (
    <input className="inline-edit" aria-label={label} autoFocus value={text} onChange={(e) => setText(e.target.value)} onFocus={(e) => e.target.select()} onBlur={commit}
      onKeyDown={(e) => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') { done.current = true; onCancel(); } }} />
  );
}

function TaskRow({ item, active, projects, onOpen, onChanged, onDeleted }) {
  const [menu, setMenu] = useFloatingMenu();
  const [editing, setEditing] = useState(false);
  if (editing) {
    return (
      <div className="conv editing">
        <InlineEdit value={item.title} label="任务名称" onCancel={() => setEditing(false)}
          onSave={async (title) => { setEditing(false); await api(`/api/conversations/${item.id}`, json('PATCH', { title })); onChanged(); }} />
      </div>
    );
  }
  const move = async (project) => { setMenu(null); await api(`/api/conversations/${item.id}`, json('PATCH', { project, move: true })); onChanged(); };
  return (
    <div className={`conv${active ? ' active' : ''}`}>
      <button className="conv-title" onClick={() => onOpen(item.id)} title={item.title}>{item.title}</button>
      <button className="conv-more" aria-label="任务操作" onClick={(e) => { e.stopPropagation(); setMenu({ x: e.clientX, y: e.clientY, view: 'main' }); }}><Icon icon={Ellipsis} size={14} /></button>
      {menu && (
        <div className="menu" style={{ left: Math.min(menu.x, window.innerWidth - 180), top: Math.min(menu.y + 8, window.innerHeight - 220) }} onClick={(e) => e.stopPropagation()}>
          {menu.view === 'main' && (
            <>
              <button onClick={() => { setMenu(null); setEditing(true); }}><Icon icon={Pencil} size={14} />重命名</button>
              <button onClick={() => setMenu({ ...menu, view: 'move' })}><Icon icon={FolderInput} size={14} />移到项目</button>
              <button className="danger" onClick={() => setMenu({ ...menu, view: 'confirm' })}><Icon icon={Trash2} size={14} />删除</button>
            </>
          )}
          {menu.view === 'move' && (
            <>
              {projects.filter((p) => p.id !== item.project).map((p) => <button key={p.id} onClick={() => move(p.id)}><Icon icon={Folder} size={14} /><span className="menu-text">{p.name}</span></button>)}
              {item.project && <button onClick={() => move(null)}>移出项目</button>}
              {!projects.length && <span className="menu-empty">还没有项目</span>}
            </>
          )}
          {menu.view === 'confirm' && (
            <>
              <button className="danger" onClick={async () => { setMenu(null); await api(`/api/conversations/${item.id}`, { method: 'DELETE' }); onDeleted(item.id); }}>确认删除？</button>
              <button onClick={() => setMenu(null)}>取消</button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function ProjectGroup({ project, tasks, open, active, onToggle, onNewTask, onChanged, renderTask }) {
  const [menu, setMenu] = useFloatingMenu();
  const [editing, setEditing] = useState(false);
  return (
    <section className="project">
      {editing ? (
        <div className="project-head editing">
          <InlineEdit value={project.name} label="项目名称" onCancel={() => setEditing(false)}
            onSave={async (name) => { setEditing(false); await api(`/api/projects/${project.id}`, json('PATCH', { name })); onChanged(); }} />
        </div>
      ) : (
        <div className={`project-head${active ? ' active' : ''}`}>
          <button className="project-name" aria-expanded={open} onClick={onToggle}>
            <Icon icon={open ? FolderOpen : Folder} /><span>{project.name}</span>
          </button>
          <div className="project-actions">
            <button aria-label="项目操作" onClick={(e) => { e.stopPropagation(); setMenu({ x: e.clientX, y: e.clientY, view: 'main' }); }}><Icon icon={Ellipsis} size={14} /></button>
            <button aria-label={`在 ${project.name} 新建任务`} onClick={onNewTask}><Icon icon={Plus} size={14} /></button>
          </div>
          {!!tasks.length && <span className="count">{tasks.length}</span>}
          {menu && (
            <div className="menu" style={{ left: Math.min(menu.x, window.innerWidth - 180), top: menu.y + 8 }} onClick={(e) => e.stopPropagation()}>
              {menu.view === 'main' ? (
                <>
                  <button onClick={() => { setMenu(null); setEditing(true); }}><Icon icon={Pencil} size={14} />重命名</button>
                  <button className="danger" onClick={() => setMenu({ ...menu, view: 'confirm' })}><Icon icon={Trash2} size={14} />删除项目</button>
                </>
              ) : (
                <>
                  <span className="menu-empty">任务会保留，只是移出项目</span>
                  <button className="danger" onClick={async () => { setMenu(null); await api(`/api/projects/${project.id}`, { method: 'DELETE' }); onChanged(); }}>确认删除</button>
                  <button onClick={() => setMenu(null)}>取消</button>
                </>
              )}
            </div>
          )}
        </div>
      )}
      {open && (
        <div className="project-tasks">
          {tasks.map(renderTask)}
          {!tasks.length && <button className="project-empty" onClick={onNewTask}>新建任务</button>}
        </div>
      )}
    </section>
  );
}

function Sidebar({ meta, conversations, projects, activeId, activeProject, onNew, onOpen, onRefresh, onDeleted, onReport, onFunnel, onCollapse }) {
  const [query, setQuery] = useState('');
  const [searching, setSearching] = useState(false);
  const [closed, setClosed] = useState({});
  const [adding, setAdding] = useState(false);
  const shown = conversations.filter((c) => !query || c.title.toLowerCase().includes(query.toLowerCase()));
  const known = new Set(projects.map((p) => p.id));
  const loose = shown.filter((c) => !c.project || !known.has(c.project));
  const renderTask = (c) => (
    <TaskRow key={c.id} item={c} active={c.id === activeId} projects={projects} onOpen={onOpen} onChanged={onRefresh} onDeleted={onDeleted} />
  );
  return (
    <aside className="side">
      <div className="side-head">
        <div className="brand"><Logo /><b>{meta?.branding?.name || 'ReportAgent'}</b></div>
        <div className="side-actions">
          <button className="icon-btn" aria-label="搜索任务" onClick={() => { setSearching(!searching); setQuery(''); }}><Icon icon={searching ? X : Search} /></button>
          <button className="icon-btn" aria-label="收起左栏" onClick={onCollapse}><Icon icon={PanelLeft} /></button>
        </div>
      </div>
      {searching && <input className="side-search" autoFocus placeholder="搜索任务" aria-label="搜索任务" value={query} onChange={(e) => setQuery(e.target.value)} />}
      <nav className="side-nav">
        <button onClick={() => onNew(null)}><Icon icon={SquarePen} />新任务</button>
        <button onClick={onReport}><Icon icon={FileText} />生成报告</button>
        {meta?.has_funnel && <button onClick={onFunnel}><Icon icon={Filter} />漏斗分析</button>}
      </nav>
      <div className="history">
        <div className="section-head">
          <span>项目</span>
          <button className="icon-btn tiny" aria-label="新建项目" onClick={() => setAdding(true)}><Icon icon={FolderPlus} size={14} /></button>
        </div>
        {adding && (
          <div className="project-head editing">
            <InlineEdit value="" label="项目名称" onCancel={() => setAdding(false)}
              onSave={async (name) => { setAdding(false); if (name.trim()) { await api('/api/projects', json('POST', { name })); onRefresh(); } }} />
          </div>
        )}
        {!projects.length && !adding && <button className="project-empty" onClick={() => setAdding(true)}>新建项目，把相关任务放在一起</button>}
        {projects.map((p) => {
          const tasks = shown.filter((c) => c.project === p.id);
          if (query && !tasks.length) return null;
          return (
            <ProjectGroup key={p.id} project={p} tasks={tasks} open={!closed[p.id] || !!query} active={activeProject === p.id && !activeId}
              onToggle={() => setClosed({ ...closed, [p.id]: !closed[p.id] })} onNewTask={() => onNew(p.id)} onChanged={onRefresh} renderTask={renderTask} />
          );
        })}
        <div className="section-head loose"><span>任务</span></div>
        {!loose.length && <p className="empty">{query ? '没有匹配的任务' : '还没有任务'}</p>}
        {loose.map(renderTask)}
      </div>
      {meta && <p className="side-foot">{meta.name}<br />销售数据更新至 {meta.latest}</p>}
    </aside>
  );
}

// ---------- 消息 ----------
const Rich = ({ text }) => text.split(/\*\*(.+?)\*\*/).map((part, i) => (i % 2 ? <strong key={i}>{part}</strong> : part));

function Chart({ result }) {
  const { chart, columns, rows, display } = result;
  const y = columns.find((c) => c.key === chart.y);
  const points = rows.map((r, i) => ({ x: r[chart.x], y: r[chart.y], d: display[i][chart.y] })).filter((p) => p.y !== null && p.y !== undefined);
  if (!points.length) return null;
  if (chart.type === 'line') {
    const W = 640, H = 190, L = 12, R = 12, T = 18, B = 24;
    const min = Math.min(...points.map((p) => p.y)), max = Math.max(...points.map((p) => p.y)), span = max - min || 1;
    const X = (i) => L + (i * (W - L - R)) / Math.max(points.length - 1, 1);
    const Y = (v) => T + (1 - (v - min) / span) * (H - T - B);
    const lastI = points.length - 1;
    return (
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${y.label} 趋势`}>
        <line x1={L} x2={W - R} y1={H - B} y2={H - B} className="axis" />
        <path d={points.map((p, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)} ${Y(p.y).toFixed(1)}`).join(' ')} className="line" />
        {points.map((p, i) => (
          <g key={p.x}>
            <circle cx={X(i)} cy={Y(p.y)} r={i === lastI ? 4 : 10} className={i === lastI ? 'dot' : 'hit'}><title>{`${p.x}：${p.d}`}</title></circle>
            {(points.length <= 14 || i % Math.ceil(points.length / 8) === 0 || i === lastI) && <text x={X(i)} y={H - 8} textAnchor="middle" className="tick">{`W${String(p.x).slice(-2)}`}</text>}
          </g>
        ))}
        <text x={X(lastI)} y={Y(points[lastI].y) - 9} textAnchor="end" className="value">{points[lastI].d}</text>
      </svg>
    );
  }
  const top = points.slice(0, 12), W = 640, lh = 24, labelW = 150, valW = 72;
  const peak = Math.max(...top.map((p) => Math.abs(p.y))) || 1;
  const negative = top.some((p) => p.y < 0), room = (W - labelW - valW) / (negative ? 2 : 1), zero = negative ? labelW + room : labelW;
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${top.length * lh + 4}`} role="img" aria-label={`${y.label} 对比`}>
      {top.map((p, i) => {
        const w = Math.max((Math.abs(p.y) / peak) * room, 2);
        const name = String(p.x);
        return (
          <g key={name}>
            <title>{`${name}：${p.d}`}</title>
            <text x={labelW - 8} y={i * lh + 16} textAnchor="end" className="tick">{name.length > 18 ? `${name.slice(0, 17)}…` : name}</text>
            <rect x={p.y < 0 ? zero - w : zero} y={i * lh + 6} width={w} height={13} rx="3" className="bar" />
            <text x={W - 4} y={i * lh + 16} textAnchor="end" className="value">{p.d}</text>
          </g>
        );
      })}
    </svg>
  );
}

function Result({ result, onOpenFunnel }) {
  const more = result.total_rows > result.rows.length;
  return (
    <div className="result">
      <h4>{result.title}</h4>
      {result.note && <p className="warn">{result.note}</p>}
      {result.chart && <Chart result={result} />}
      <div className="table-wrap">
        <table>
          <thead><tr>{result.columns.map((c) => <th key={c.key} className={c.kind === 'text' ? 'txt' : ''}>{c.label}</th>)}</tr></thead>
          <tbody>
            {result.display.map((row, i) => (
              <tr key={i}>{result.columns.map((c) => <td key={c.key} className={c.kind === 'text' ? 'txt' : ''}>{row[c.key]}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="meta">
        {result.open && <button className="chip" onClick={() => onOpenFunnel(result.open.url, result.open.title)}>打开漏斗看板，继续下钻</button>}
        {more && <div>共 {result.total_rows} 行，这里显示前 {result.rows.length} 行。</div>}
        {result.assumptions?.length > 0 && <div>假设：{result.assumptions.join('；')}</div>}
        {result.queries?.length > 0 && (
          <details>
            <summary>这个数怎么算的（{result.queries.length} 条 SQL）</summary>
            {result.queries.map((q, i) => <div key={i}><div>{q.purpose}：{q.rows} 行，{q.ms} ms</div><pre>{q.sql}</pre></div>)}
          </details>
        )}
      </div>
    </div>
  );
}

function WebSources({ result }) {
  return (
    <div className="result">
      <h4>{result.title}</h4>
      <ol className="sources">
        {result.items.map((x) => (
          <li key={x.url}>
            <a href={x.url} target="_blank" rel="noopener noreferrer">{x.title}</a>
            <span>{[x.media, x.date].filter(Boolean).join(' · ')}</span>
          </li>
        ))}
      </ol>
      <p className="assume">外部网页内容未经核实，不代表内部数据。</p>
    </div>
  );
}

function Collapsible({ title, defaultOpen = true, children }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="collapsible">
      <button className="step-head" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span>{title}</span><Icon icon={open ? ChevronDown : ChevronRight} size={12} />
      </button>
      {open && children}
    </div>
  );
}

const PILL = { running: '执行中', done: '执行完成', retry: '正在调整', failed: '执行异常', stopped: '已终止' };

/** 把事件流折叠成可渲染的状态：实时流和历史回放走同一段逻辑。 */
function fold(events) {
  const s = { rewrite: null, notices: [], matched: null, thought: '', thinking: false, tasks: [], results: [], answer: null, error: null, stopped: false };
  for (const e of events) {
    if (e.type === 'rewrite') s.rewrite = e.text;
    else if (e.type === 'notice') s.notices.push(e.text);
    else if (e.type === 'matched') s.matched = e.question;
    else if (e.type === 'thinking') { s.thinking = e.status === 'running'; if (e.text) s.thought = e.text; }
    else if (e.type === 'task') {
      if (e.status === 'running') s.tasks.push({ ...e });
      else { const t = s.tasks.find((x) => x.id === e.id); if (t) Object.assign(t, { status: e.status, message: e.message }); }
    } else if (e.type === 'result') s.results.push(e);
    else if (e.type === 'answer') s.answer = e;
    else if (e.type === 'error') s.error = e.message;
    else if (e.type === 'stopped') s.stopped = true;
  }
  return s;
}

function BotMessage({ events, live, onAsk, onOpenReport, onOpenFunnel }) {
  const s = useMemo(() => fold(events), [events]);
  const [feedback, setFeedback] = useState(null);
  const pending = s.tasks.filter((t) => t.status === 'running').length;
  const status = s.thinking ? '辅助思考 Agent 正在思考' : pending ? '正在执行工具' : '意图识别 Agent 正在处理';
  return (
    <div className="msg-bot">
      <div className="bot-orb" aria-hidden="true">{live ? <FluidAgentOrb preset="monochrome" state={s.thinking ? 'thinking' : 'searching'} style={{ width: 24, height: 24 }} animateEntrance={false} /> : <Logo size={22} />}</div>
      <div className="bot-body">
        {s.notices.map((n) => <p className="warn" key={n}>{n}</p>)}
        {s.rewrite && <div className="step-note">问题改写 Agent 理解为：{s.rewrite}</div>}
        {s.matched && <div className="step-note">从问答库匹配到相似问题：{s.matched}</div>}
        {s.thought && <Collapsible title="辅助思考 Agent 已完成"><div className="thought">{s.thought}</div></Collapsible>}
        {s.tasks.length > 0 && (
          <Collapsible key={live ? 'live' : 'done'} defaultOpen={live}
            title={pending ? `拆解为 ${s.tasks.length} 个任务，正在执行（${s.tasks.length - pending}/${s.tasks.length}）` : `已完成 ${s.tasks.length} 个任务`}>
            <div className="tasks">
              {s.tasks.map((t) => {
                const status2 = t.status === 'running' && !live ? 'stopped' : t.status;
                return (
                  <div className={`task ${status2}`} key={t.id}>
                    <div className="h"><span>{t.label} {t.id}</span><span className={`pill ${status2}`}>{PILL[status2]}</span></div>
                    <p>{t.status === 'retry' ? `${t.message} 正在尝试其他方案…` : t.message || t.text}</p>
                    <div className="bar"><i style={{ width: t.status === 'running' ? '55%' : '100%' }} /></div>
                  </div>
                );
              })}
            </div>
          </Collapsible>
        )}
        {s.answer && <div className="answer"><Rich text={s.answer.text} /></div>}
        {s.answer?.mode === 'fallback' && <p className="warn">模型生成的文字未通过数字校验，已换成规则生成的结论。</p>}
        {s.results.map((r, i) => (r.kind === 'web' ? <WebSources key={i} result={r} /> : r.kind === 'report' ? (
          <div className="report-card" key={i}>
            <div><b>{r.report.title}</b>{r.assumptions?.length > 0 && <div className="assume">{r.assumptions.join('；')}</div>}</div>
            <button className="chip" onClick={() => onOpenReport(r.report)}>查看报告</button>
          </div>
        ) : <Result key={i} result={r} onOpenFunnel={onOpenFunnel} />))}
        {s.error && <p className="err" role="alert">{s.error}</p>}
        {s.stopped && <p className="warn">任务已终止。</p>}
        {live && <div className="working"><span className="dots"><i /><i /><i /></span>{status}</div>}
        {!live && s.answer && (
          <div className="fb">
            <button aria-label="有帮助" className={feedback === 'up' ? 'on' : ''} onClick={() => setFeedback('up')}><Icon icon={feedback === 'up' ? Check : ThumbsUp} size={14} /></button>
            <button aria-label="不准确" className={feedback === 'down' ? 'on' : ''} onClick={() => setFeedback('down')}><Icon icon={ThumbsDown} size={14} /></button>
            {feedback === 'down' && <span>已记录。可以直接告诉我哪里不对。</span>}
          </div>
        )}
        {!live && s.answer?.suggestions?.length > 0 && (
          <div className="chips">{s.answer.suggestions.map((q) => <button className="chip" key={q} onClick={() => onAsk(q)}>{q}</button>)}</div>
        )}
      </div>
    </div>
  );
}

// ---------- 输入框 ----------
function Composer({ meta, busy, assist, onAssist, web, onWeb, onSend, onStop, onReport, big, project, onClearProject }) {
  const [text, setText] = useState('');
  const box = useRef(null);
  const resize = () => { const t = box.current; if (t) { t.style.height = 'auto'; t.style.height = `${Math.min(t.scrollHeight, 140)}px`; } };
  useEffect(resize, [text]);
  const send = () => { if (text.trim()) { onSend(text); setText(''); } };
  return (
    <div className={`composer${big ? ' big' : ''}`}>
      <div className="tray">
        {project && (
          <button className="tray-project" onClick={onClearProject} disabled={!onClearProject} title={onClearProject ? '不放进这个项目' : project.name}>
            <Icon icon={Folder} size={13} />{project.name}{onClearProject && <Icon icon={X} size={11} />}
          </button>
        )}
        <span className="tray-item">{meta?.name || '连接数仓中'}</span>
        {meta?.synthetic && <span className="badge">模拟数据</span>}
      </div>
      <div className="box">
        <textarea ref={box} rows={1} value={text} placeholder="问问数据，或者让我生成周报、看漏斗" aria-label="输入问题" onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); if (!busy) send(); } }} />
        <div className="box-row">
          <button className="switch" role="switch" aria-checked={assist} title="开启后先拆解问题再取数，适合模糊问题" onClick={() => onAssist(!assist)}><i />辅助思考</button>
          {meta?.web_search && <button className="switch" role="switch" aria-checked={web} title="开启后可以查询外部公开信息" onClick={() => onWeb(!web)}><i />联网搜索</button>}
          <button className="chip" type="button" onClick={onReport}><Icon icon={FileText} size={14} />生成报告</button>
          <button className="send" aria-label={busy ? '停止' : '发送'} disabled={!busy && !text.trim()} onClick={busy ? onStop : send}><Icon icon={busy ? Square : ArrowUp} color="#fff" /></button>
        </div>
      </div>
      <p className="disclaimer">AI 可能出错，请核对重要信息。表格里的数字由代码计算。</p>
    </div>
  );
}

// ---------- 右侧面板 ----------
function Panel({ panel, serverPdf, onClose, onAsk }) {
  const frame = useRef(null);
  const [selection, setSelection] = useState(null);
  const [links, setLinks] = useState({});
  const url = panel.url;
  useEffect(() => { setLinks({ open: url, pdf: panel.pdf }); setSelection(null); }, [url, panel.pdf]);
  const onLoad = () => {
    let doc;
    try { doc = frame.current.contentDocument; } catch { return; }
    if (!doc) return;
    const path = doc.location?.pathname || '';
    if (path.startsWith('/funnel')) {
      const current = path + doc.location.search;
      setLinks({ open: current, pdf: current.replace('/funnel', '/funnel/pdf') });
    }
    doc.addEventListener('mousedown', () => setSelection(null));
    doc.addEventListener('mouseup', () => {
      const text = doc.getSelection()?.toString().trim();
      if (!text || text.length < 2 || text.length > 300) return;
      const rect = doc.getSelection().getRangeAt(0).getBoundingClientRect(), box = frame.current.getBoundingClientRect();
      setSelection({ text, x: box.left + rect.left, y: Math.max(box.top + rect.top - 34, 56) });
    });
  };
  return (
    <section className="panel-right" aria-label="报告面板">
      <header>
        <b title={panel.title}>{panel.title}</b>
        {!panel.loading && (
          <>
            {serverPdf
              ? <a className="chip" href={links.pdf} target="_blank" rel="noopener"><Icon icon={Download} size={14} />PDF</a>
              : <button className="chip" title="在打印窗口选择“存储为 PDF”" onClick={() => frame.current?.contentWindow?.print()}><Icon icon={Download} size={14} />PDF</button>}
            <a className="icon-btn" href={links.open} target="_blank" rel="noopener" aria-label="新窗口打开"><Icon icon={ExternalLink} /></a>
          </>
        )}
        <button className="icon-btn" aria-label="关闭面板" onClick={onClose}><Icon icon={X} /></button>
      </header>
      {panel.loading ? (
        <div className="panel-loading">
          <FluidAgentOrb preset="monochrome" state="searching" animateEntrance={false} style={{ width: 72, height: 72 }} />
          <p>正在从数仓取数并生成报告…</p>
        </div>
      ) : <iframe ref={frame} src={url} title={panel.title} sandbox="allow-same-origin allow-forms allow-modals" onLoad={onLoad} />}
      {panel.error && <p className="err panel-error" role="alert">{panel.error}</p>}
      {selection && (
        <button className="ask-sel" style={{ left: selection.x, top: selection.y }}
          onClick={() => { onAsk(`关于报告“${panel.title}”里的这段内容：“${selection.text}”，请解释原因。`); setSelection(null); }}>
          追问这段
        </button>
      )}
    </section>
  );
}

function ReportDialog({ meta, onClose, onCreate }) {
  const [form, setForm] = useState({ store: meta.stores[0]?.id || '', category: meta.default_category || meta.categories[0] || '', week: meta.week, channel: meta.default_channel, focus: meta.default_focus });
  const [error, setError] = useState('');
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });
  const L = meta.labels;
  return (
    <div className="modal" onKeyDown={(e) => { if (e.key === 'Escape') onClose(); }}>
      <form className="dialog" onSubmit={(e) => { e.preventDefault(); onCreate(form).catch((err) => setError(err.message)); }}>
        <h3>生成业绩报告</h3>
        <p>选好范围就能出报告，不经过对话。生成后在右侧打开。</p>
        <div className="row">
          <label className="field">{L.store}<select autoFocus value={form.store} onChange={set('store')}>{meta.stores.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
          <label className="field">{L.category}<select value={form.category} onChange={set('category')}>{meta.categories.map((c) => <option key={c}>{c}</option>)}</select></label>
        </div>
        <div className="row">
          <label className="field">周次（ISO）<input value={form.week} onChange={set('week')} pattern="\d{6}" required /></label>
          <label className="field">下钻{L.channel}<select value={form.channel} onChange={set('channel')}>{meta.channels.map((c) => <option key={c}>{c}</option>)}</select></label>
        </div>
        <label className="field">分析指标<select value={form.focus} onChange={set('focus')}><option value="sales">Sales 销售额</option><option value="qty">Qty 销量</option></select></label>
        <div className="dialog-foot">
          <span className="err" role="alert">{error}</span>
          <button type="button" className="chip" onClick={onClose}>取消</button>
          <button className="send-text">生成</button>
        </div>
      </form>
    </div>
  );
}

// ---------- 应用 ----------
export default function App() {
  const [meta, setMeta] = useState(null);
  const [bootError, setBootError] = useState('');
  const [conversations, setConversations] = useState([]);
  const [projects, setProjects] = useState([]);
  const [projectId, setProjectId] = useState(null);
  const projectRef = useRef(null);
  projectRef.current = projectId;
  const [cid, setCid] = useState(null);
  const [messages, setMessages] = useState([]);
  const [busy, setBusy] = useState(false);
  const [assist, setAssist] = useState(true);
  const [web, setWeb] = useState(false);
  const [panel, setPanel] = useState(null);
  const [dialog, setDialog] = useState(false);
  const [sideOpen, setSideOpen] = useState(window.innerWidth > 1000);
  const [page, setPage] = useState(0);
  const controller = useRef(null);
  const scroller = useRef(null);
  const cidRef = useRef(null);
  cidRef.current = cid;

  const refresh = useCallback(() => Promise.all([
    api('/api/conversations').then(setConversations),
    api('/api/projects').then(setProjects),
  ]).catch(() => {}), []);
  useEffect(() => {
    if (meta?.branding?.name) document.title = `${meta.branding.name} ${meta.branding.product || ''}`.trim();
    if (meta?.branding?.accent) document.documentElement.style.setProperty('--accent', meta.branding.accent);
  }, [meta]);
  useEffect(() => {
    api('/api/meta').then(setMeta).catch((e) => setBootError(`连接数仓失败：${e.message}`));
    refresh();
  }, [refresh]);
  useEffect(() => {
    const el = scroller.current;
    if (el && el.scrollHeight - el.scrollTop - el.clientHeight < 200) el.scrollTop = el.scrollHeight;
  }, [messages]);

  const openReport = useCallback((report) => {
    setPanel({ title: report.title, url: `/reports/${report.id}`, pdf: `/reports/${report.id}/pdf` });
    if (window.innerWidth < 1300) setSideOpen(false);
  }, []);
  const openFunnel = useCallback((url = '/funnel', title = '漏斗分析') => {
    setPanel({ title, url, pdf: url.replace('/funnel', '/funnel/pdf') });
    if (window.innerWidth < 1300) setSideOpen(false);
  }, []);

  const ask = useCallback(async (raw) => {
    const question = raw.trim();
    if (!question || controller.current) return;
    setMessages((m) => [...m, { role: 'user', content: question }, { role: 'assistant', events: [], live: true }]);
    setBusy(true);
    const ctrl = new AbortController();
    controller.current = ctrl;
    const push = (event) => setMessages((m) => {
      const copy = m.slice(), last = copy[copy.length - 1];
      copy[copy.length - 1] = { ...last, events: [...last.events, event] };
      return copy;
    });
    try {
      const r = await fetch('/api/chat', { ...json('POST', { message: question, conversation: cidRef.current, project: projectRef.current, assist, web }), signal: ctrl.signal });
      if (!r.ok || !r.body) {
        let detail = `请求失败（${r.status}）`;
        try { detail = (await r.json()).detail || detail; } catch { /* 非 JSON */ }
        throw new Error(detail);
      }
      const reader = r.body.pipeThrough(new TextDecoderStream()).getReader();
      let buffer = '';
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += value;
        let cut;
        while ((cut = buffer.indexOf('\n\n')) >= 0) {
          const line = buffer.slice(0, cut);
          buffer = buffer.slice(cut + 2);
          if (!line.startsWith('data: ')) continue;
          const event = JSON.parse(line.slice(6));
          if (event.type === 'conversation') { setCid(event.id); cidRef.current = event.id; }
          else if (event.type !== 'end') {
            push(event);
            // 一开始生成报告就打开右侧面板；报告好了自动切到内容
            if (event.type === 'task' && event.status === 'running' && event.label === '生成报告') {
              setPanel({ title: '正在生成报告', loading: true });
              if (window.innerWidth < 1300) setSideOpen(false);
            }
            if (event.type === 'result' && event.kind === 'report') openReport(event.report);
          }
        }
      }
    } catch (err) {
      push(err.name === 'AbortError' ? { type: 'stopped' } : { type: 'error', message: err.message });
      setPanel((p) => (p?.loading ? null : p));
    }
    controller.current = null;
    setBusy(false);
    setMessages((m) => m.map((x, i) => (i === m.length - 1 ? { ...x, live: false } : x)));
    setPanel((p) => (p?.loading ? null : p));
    refresh();
  }, [assist, web, openReport, refresh]);

  const newChat = (project = null) => { if (busy) return; setCid(null); setProjectId(project); setMessages([]); setPanel(null); refresh(); };
  const openConversation = async (id) => {
    if (busy) return;
    const data = await api(`/api/conversations/${id}`);
    setCid(id);
    setProjectId(data.project || null);
    setMessages(data.messages.map((m) => (m.role === 'user' ? { role: 'user', content: m.content } : { role: 'assistant', events: m.blocks, live: false })));
    const report = [...data.messages].reverse().flatMap((m) => [...(m.blocks || [])].reverse()).find((b) => b.kind === 'report');
    if (report) openReport(report.report); else setPanel(null);
    if (window.innerWidth <= 1000) setSideOpen(false);
  };
  const createReport = async (form) => {
    setDialog(false);
    setPanel({ title: '正在生成报告', loading: true });
    if (window.innerWidth < 1300) setSideOpen(false);
    try {
      const report = await api('/api/reports', json('POST', { ...form, project: projectId }));
      openReport(report);
      await refresh();
      if (!busy && report.conversation) await openConversation(report.conversation);
    } catch (err) {
      setDialog(true);
      setPanel(null);
      throw err;
    }
  };

  const examples = useMemo(() => {
    const list = meta?.examples || [];
    const types = [...new Set(list.map((e) => e.type))];
    return types.slice(0, 4).map((t) => { const pool = list.filter((e) => e.type === t); return pool[page % pool.length]; });
  }, [meta, page]);

  const empty = messages.length === 0;
  const currentProject = projects.find((p) => p.id === projectId) || null;
  const composer = (
    <Composer meta={meta} busy={busy} assist={assist} onAssist={setAssist} web={web} onWeb={setWeb} onSend={ask} onStop={() => controller.current?.abort()} onReport={() => setDialog(true)} big={empty}
      project={currentProject} onClearProject={cid ? null : () => setProjectId(null)} />
  );
  return (
    <div className="app">
      {sideOpen && (
        <Sidebar meta={meta} conversations={conversations} projects={projects} activeId={cid} activeProject={projectId} onNew={newChat} onOpen={openConversation} onRefresh={refresh}
          onDeleted={(id) => { if (id === cid) newChat(projectId); else refresh(); }} onReport={() => setDialog(true)} onFunnel={() => openFunnel()} onCollapse={() => setSideOpen(false)} />
      )}
      <main className="center">
        <div className="center-top">
          {!sideOpen && <button className="icon-btn" aria-label="展开左栏" onClick={() => setSideOpen(true)}><Icon icon={Menu} /></button>}
          {!sideOpen && <><Logo /><b>{meta?.branding?.name || 'ReportAgent'}</b></>}
          <span className="spacer" />
          {!empty && <button className="icon-btn" aria-label="新任务" onClick={() => newChat(projectId)} disabled={busy}><Icon icon={Plus} /></button>}
          {!panel && meta?.has_funnel && <button className="icon-btn" aria-label="打开漏斗面板" onClick={() => openFunnel()}><Icon icon={PanelRight} /></button>}
        </div>
        {empty ? (
          <div className="home">
            <div className="hero">
              <Logo size={44} />
              <h1>{currentProject ? `在“${currentProject.name}”里看点什么？` : '今天想看点什么？'}</h1>
            </div>
            {bootError && <p className="err" role="alert">{bootError}</p>}
            <div className="home-body">
              <ul className="suggest">
                {examples.map((e) => <li key={e.text}><button onClick={() => ask(e.text)}><span>{e.type}</span>{e.text}</button></li>)}
              </ul>
              {examples.length > 0 && <button className="link" onClick={() => setPage(page + 1)}>换一批</button>}
              {composer}
            </div>
          </div>
        ) : (
          <>
            <div className="scroll" ref={scroller}>
              <div className="thread">
                {messages.map((m, i) => (m.role === 'user'
                  ? <div className="msg-user" key={i}><div>{m.content}</div></div>
                  : <BotMessage key={i} events={m.events} live={m.live} onAsk={ask} onOpenReport={openReport} onOpenFunnel={openFunnel} />))}
              </div>
            </div>
            {composer}
          </>
        )}
      </main>
      {panel && <Panel panel={panel} serverPdf={meta?.server_pdf} onClose={() => setPanel(null)} onAsk={ask} />}
      {dialog && meta && <ReportDialog meta={meta} onClose={() => setDialog(false)} onCreate={createReport} />}
    </div>
  );
}
