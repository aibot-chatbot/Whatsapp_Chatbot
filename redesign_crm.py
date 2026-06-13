import re

path = r'C:\Users\User\PycharmProjects\python-whatsapp-bot-main\frontend\crm.html'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

print(f"Original size: {len(content)} chars")

# ===== 1. Insert new CSS before </style> =====
insert_point = content.index('</style>')
new_styles = '''
        /* ===== Business Snapshot Bar ===== */
        .snapshot-bar {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 14px;
            margin-bottom: 24px;
        }
        .snapshot-item {
            background: var(--card-bg);
            backdrop-filter: blur(10px);
            border: 1px solid var(--glass-border);
            border-radius: 14px;
            padding: 16px 18px;
            display: flex;
            flex-direction: column;
            gap: 2px;
            transition: all 0.25s ease;
        }
        .snapshot-item:hover {
            transform: translateY(-2px);
            border-color: rgba(255,255,255,0.2);
        }
        .snapshot-label {
            color: var(--text-dim);
            font-size: 0.72rem;
            text-transform: uppercase;
            letter-spacing: 0.6px;
            font-weight: 600;
        }
        .snapshot-value {
            font-size: 1.6rem;
            font-weight: 700;
            line-height: 1.2;
        }
        .snapshot-trend {
            font-size: 0.72rem;
            color: var(--text-dim);
            margin-top: 2px;
        }
        .snapshot-highlight { border-color: rgba(59,130,246,0.3); background: rgba(59,130,246,0.07); }
        .snapshot-highlight .snapshot-value { color: #93c5fd; }
        .snapshot-warning { border-color: rgba(245,158,11,0.28); background: rgba(245,158,11,0.06); }
        .snapshot-warning .snapshot-value { color: #fbbf24; }
        .snapshot-danger { border-color: rgba(239,68,68,0.25); background: rgba(239,68,68,0.06); }
        .snapshot-danger .snapshot-value { color: #f87171; }
        .snapshot-success { border-color: rgba(16,185,129,0.25); background: rgba(16,185,129,0.06); }
        .snapshot-success .snapshot-value { color: #34d399; }

        /* ===== Action Board ===== */
        .action-board {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 16px;
            margin-bottom: 24px;
        }
        @media (max-width: 900px) { .action-board { grid-template-columns: 1fr; } }
        .action-column {
            background: var(--card-bg);
            backdrop-filter: blur(10px);
            border: 1px solid var(--glass-border);
            border-radius: 16px;
            padding: 18px;
            display: flex;
            flex-direction: column;
            gap: 10px;
            transition: all 0.25s ease;
            cursor: pointer;
        }
        .action-column:hover { transform: translateY(-2px); }
        .action-column:focus-visible { outline: 2px solid rgba(59,130,246,0.85); outline-offset: 2px; }
        .action-column.active-filter { box-shadow: 0 0 0 1px currentColor; }
        .action-column-overdue { border-color: rgba(239,68,68,0.2); }
        .action-column-overdue:hover, .action-column-overdue.active-filter { border-color: rgba(239,68,68,0.55); }
        .action-column-today { border-color: rgba(245,158,11,0.2); }
        .action-column-today:hover, .action-column-today.active-filter { border-color: rgba(245,158,11,0.55); }
        .action-column-upcoming { border-color: rgba(59,130,246,0.2); }
        .action-column-upcoming:hover, .action-column-upcoming.active-filter { border-color: rgba(59,130,246,0.55); }
        .action-col-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
        .action-col-title { font-size: 0.88rem; font-weight: 700; }
        .action-col-count { font-size: 1.1rem; font-weight: 700; padding: 2px 10px; border-radius: 999px; background: rgba(255,255,255,0.06); min-width: 28px; text-align: center; }
        .action-col-overdue .action-col-title { color: #f87171; }
        .action-col-overdue .action-col-count { color: #f87171; background: rgba(239,68,68,0.12); }
        .action-col-today .action-col-title { color: #fbbf24; }
        .action-col-today .action-col-count { color: #fbbf24; background: rgba(245,158,11,0.12); }
        .action-col-upcoming .action-col-title { color: #93c5fd; }
        .action-col-upcoming .action-col-count { color: #93c5fd; background: rgba(59,130,246,0.12); }
        .action-item { padding: 8px 10px; border-radius: 10px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.05); font-size: 0.85rem; line-height: 1.3; cursor: pointer; transition: background 0.2s; }
        .action-item:hover { background: rgba(255,255,255,0.07); }
        .action-item-name { font-weight: 600; color: var(--text-main); }
        .action-item-reason { color: var(--text-dim); font-size: 0.78rem; margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .action-empty { color: var(--text-dim); font-size: 0.82rem; text-align: center; padding: 16px 0; }

        /* ===== Pipeline ===== */
        .pipeline-bar { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 24px; }
        @media (max-width: 768px) { .pipeline-bar { grid-template-columns: repeat(2, 1fr); } }
        .pipeline-stage { background: var(--card-bg); backdrop-filter: blur(10px); border: 1px solid var(--glass-border); border-radius: 12px; padding: 12px 14px; text-align: center; transition: all 0.25s ease; cursor: pointer; position: relative; }
        .pipeline-stage:hover { transform: translateY(-2px); border-color: rgba(255,255,255,0.2); }
        .pipeline-stage:focus-visible { outline: 2px solid rgba(59,130,246,0.85); outline-offset: 2px; }
        .pipeline-stage.active-filter { border-color: rgba(59,130,246,0.6); box-shadow: 0 0 0 1px rgba(59,130,246,0.2); }
        .pipeline-stage + .pipeline-stage::before { content: "\\2192"; position: absolute; left: -10px; top: 50%; transform: translateY(-50%); color: var(--text-dim); font-size: 1rem; }
        @media (max-width: 768px) { .pipeline-stage:nth-child(2)::before { display: none; } }
        .pipeline-stage-label { color: var(--text-dim); font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600; }
        .pipeline-stage-value { font-size: 1.3rem; font-weight: 700; margin-top: 4px; }
        .pipeline-stage-new .pipeline-stage-value { color: #93c5fd; }
        .pipeline-stage-progress .pipeline-stage-value { color: #fbbf24; }
        .pipeline-stage-contacted .pipeline-stage-value { color: #34d399; }
        .pipeline-stage-closed .pipeline-stage-value { color: var(--text-dim); }

        /* ===== AI Insight Box ===== */
        .insight-box { background: linear-gradient(135deg, rgba(59,130,246,0.08), rgba(16,185,129,0.06)); border: 1px solid rgba(59,130,246,0.2); border-radius: 14px; padding: 16px 20px; margin-bottom: 24px; display: flex; align-items: flex-start; gap: 14px; }
        .insight-icon { width: 36px; height: 36px; border-radius: 10px; background: rgba(59,130,246,0.12); display: flex; align-items: center; justify-content: center; font-size: 1.1rem; flex-shrink: 0; }
        .insight-content { flex: 1; min-width: 0; }
        .insight-title { font-size: 0.78rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-dim); margin-bottom: 4px; }
        .insight-text { font-size: 0.9rem; color: var(--text-main); line-height: 1.5; }

        /* ===== Enhanced Table ===== */
        .crm-leads-section { background: var(--card-bg); backdrop-filter: blur(10px); border: 1px solid var(--glass-border); border-radius: 18px; padding: 20px 24px; }
        .table-wrap { overflow-x: auto; }
        .enhanced-table { width: 100%; border-collapse: separate; border-spacing: 0; min-width: 800px; }
        .enhanced-table th { text-align: left; padding: 10px 12px; border-bottom: 1px solid rgba(255,255,255,0.06); color: var(--text-dim); font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.6px; font-weight: 600; white-space: nowrap; }
        .enhanced-table td { padding: 10px 12px; border-bottom: 1px solid rgba(255,255,255,0.04); font-size: 0.88rem; vertical-align: middle; transition: background 0.15s; }
        .enhanced-table tr:hover td { background: rgba(255,255,255,0.02); }
        .enhanced-table tr:last-child td { border-bottom: none; }
        .icon-btn { width: 32px; height: 32px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.1); background: rgba(255,255,255,0.04); color: var(--text-dim); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; font-size: 0.9rem; transition: all 0.2s; padding: 0; }
        .icon-btn:hover { background: rgba(255,255,255,0.1); color: var(--text-main); border-color: rgba(255,255,255,0.2); }
        .icon-btn.save-ok { color: var(--accent); border-color: rgba(16,185,129,0.3); }
        .follow-up-cell { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
        .follow-up-cell input[type="date"] { background: rgba(15,23,42,0.5); border: 1px solid rgba(255,255,255,0.08); border-radius: 7px; padding: 4px 8px; color: var(--text-main); font-size: 0.82rem; font-family: inherit; outline: none; width: 130px; }
        .follow-up-cell input[type="date"]:focus { border-color: rgba(59,130,246,0.5); }
        .inline-select { background: rgba(15,23,42,0.5); border: 1px solid rgba(255,255,255,0.08); border-radius: 7px; padding: 4px 8px; color: var(--text-main); font-size: 0.82rem; font-family: inherit; outline: none; cursor: pointer; }
        .inline-select:focus { border-color: rgba(59,130,246,0.5); }
        .inline-input { background: rgba(15,23,42,0.5); border: 1px solid rgba(255,255,255,0.08); border-radius: 7px; padding: 4px 8px; color: var(--text-main); font-size: 0.82rem; font-family: inherit; outline: none; width: 100px; }
        .inline-input:focus { border-color: rgba(59,130,246,0.5); }
        .save-feedback-inline { font-size: 0.72rem; min-width: 40px; color: var(--text-dim); }
        .save-feedback-inline.success { color: var(--accent); }
        .save-feedback-inline.error { color: var(--danger); }
'''

content = content[:insert_point] + new_styles + content[insert_point:]
print("CSS inserted")

# ===== 2. REPLACE MAIN HTML =====
main_marker = '<main class="main-container">'
main_start = content.index(main_marker)
main_end = content.index('</main>', main_start) + len('</main>')

new_html = '''    <main class="main-container">
        <div class="header" style="margin-bottom:24px;">
            <div>
                <h1 id="page-title" style="font-size:1.7rem;margin-bottom:4px;">CRM / Leads</h1>
                <p style="font-size:0.88rem;margin:0;">Customer follow-up records and lead management</p>
            </div>
            <div class="glass-card status-pill" style="padding:8px 18px;">
                <span id="bot-name">Loading bot...</span>
            </div>
        </div>

        <div class="snapshot-bar">
            <div class="snapshot-item snapshot-highlight">
                <div class="snapshot-label">Total Leads</div>
                <div class="snapshot-value" id="crm-total-count">...</div>
                <div class="snapshot-trend">All time</div>
            </div>
            <div class="snapshot-item snapshot-success">
                <div class="snapshot-label">Active Leads</div>
                <div class="snapshot-value" id="crm-active-count">...</div>
                <div class="snapshot-trend">New + In Progress</div>
            </div>
            <div class="snapshot-item snapshot-warning">
                <div class="snapshot-label">Follow-ups Today</div>
                <div class="snapshot-value" id="crm-today-snapshot-count">...</div>
                <div class="snapshot-trend">Needs attention</div>
            </div>
            <div class="snapshot-item snapshot-danger">
                <div class="snapshot-label">Overdue</div>
                <div class="snapshot-value" id="crm-overdue-snapshot-count">...</div>
                <div class="snapshot-trend">Past follow-up date</div>
            </div>
            <div class="snapshot-item">
                <div class="snapshot-label">Closed</div>
                <div class="snapshot-value" id="crm-closed-snapshot-count">...</div>
                <div class="snapshot-trend">Resolved</div>
            </div>
        </div>

        <div class="action-board">
            <div class="action-column action-column-overdue" data-work-panel="overdue" role="button" tabindex="0" aria-pressed="false" aria-label="Overdue leads">
                <div class="action-col-header">
                    <div class="action-col-title action-col-overdue" style="display:flex;align-items:center;gap:6px;">
                        <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#ef4444;"></span>
                        Overdue
                    </div>
                    <span class="action-col-count action-col-overdue" id="work-overdue-count">...</span>
                </div>
                <div class="action-col-items" id="action-overdue-items">
                    <div class="action-empty">No overdue leads</div>
                </div>
            </div>
            <div class="action-column action-column-today" data-work-panel="today" role="button" tabindex="0" aria-pressed="false" aria-label="Follow-ups due today">
                <div class="action-col-header">
                    <div class="action-col-title action-col-today" style="display:flex;align-items:center;gap:6px;">
                        <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#f59e0b;"></span>
                        Due Today
                    </div>
                    <span class="action-col-count action-col-today" id="work-today-count">...</span>
                </div>
                <div class="action-col-items" id="action-today-items">
                    <div class="action-empty">No follow-ups due today</div>
                </div>
            </div>
            <div class="action-column action-column-upcoming" data-work-panel="upcoming" role="button" tabindex="0" aria-pressed="false" aria-label="Upcoming follow-ups">
                <div class="action-col-header">
                    <div class="action-col-title action-col-upcoming" style="display:flex;align-items:center;gap:6px;">
                        <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#3b82f6;"></span>
                        Upcoming
                    </div>
                    <span class="action-col-count action-col-upcoming" id="work-upcoming-count">...</span>
                </div>
                <div class="action-col-items" id="action-upcoming-items">
                    <div class="action-empty">No upcoming follow-ups</div>
                </div>
            </div>
        </div>

        <div class="pipeline-bar">
            <div class="pipeline-stage pipeline-stage-new" data-status-card="new" role="button" tabindex="0" aria-pressed="false">
                <div class="pipeline-stage-label">New</div>
                <div class="pipeline-stage-value" id="crm-new-count">...</div>
            </div>
            <div class="pipeline-stage pipeline-stage-progress" data-status-card="in_progress" role="button" tabindex="0" aria-pressed="false">
                <div class="pipeline-stage-label">In Progress</div>
                <div class="pipeline-stage-value" id="crm-in-progress-count">...</div>
            </div>
            <div class="pipeline-stage pipeline-stage-contacted" data-status-card="contacted" role="button" tabindex="0" aria-pressed="false">
                <div class="pipeline-stage-label">Contacted</div>
                <div class="pipeline-stage-value" id="crm-contacted-count">...</div>
            </div>
            <div class="pipeline-stage pipeline-stage-closed" data-status-card="closed" role="button" tabindex="0" aria-pressed="false">
                <div class="pipeline-stage-label">Closed</div>
                <div class="pipeline-stage-value" id="crm-closed-count">...</div>
            </div>
        </div>

        <div class="insight-box" id="insight-box">
            <div class="insight-icon">🧠</div>
            <div class="insight-content">
                <div class="insight-title">AI Insight</div>
                <div class="insight-text" id="insight-text">Loading lead insights...</div>
            </div>
        </div>

        <div class="crm-leads-section">
            <div class="crm-section-header">
                <div>
                    <h2>Leads</h2>
                    <p>Manage and update customer follow-up records</p>
                </div>
            </div>
            <div class="crm-filters">
                <div class="crm-filter-row crm-filter-selects">
                    <select class="crm-select" id="crm-status-filter" aria-label="Filter by status">
                        <option value="">All Statuses</option>
                        <option value="new">New</option>
                        <option value="in_progress">In Progress</option>
                        <option value="contacted">Contacted</option>
                        <option value="closed">Closed</option>
                    </select>
                    <select class="crm-select" id="crm-priority-filter" aria-label="Filter by priority">
                        <option value="">All Priorities</option>
                        <option value="high">High</option>
                        <option value="medium">Medium</option>
                        <option value="low">Low</option>
                    </select>
                    <select class="crm-select" id="crm-type-filter" aria-label="Filter by type">
                        <option value="">All Types</option>
                        <option value="follow_up">Follow-up</option>
                        <option value="staff_attention">Staff Attention</option>
                        <option value="negative_feedback">Negative Feedback</option>
                    </select>
                    <select class="crm-select" id="crm-follow-up-filter" aria-label="Filter by follow-up date">
                        <option value="">All Follow-ups</option>
                        <option value="today">Due Today</option>
                        <option value="overdue">Overdue</option>
                        <option value="upcoming">Upcoming</option>
                        <option value="none">No Follow-up Date</option>
                    </select>
                    <select class="crm-select" id="crm-assignment-filter" aria-label="Filter by assignment">
                        <option value="">All Assignment</option>
                        <option value="assigned">Assigned</option>
                        <option value="unassigned">Unassigned</option>
                    </select>
                </div>
                <div class="crm-filter-row crm-filter-search-row">
                    <input class="crm-select crm-search" id="crm-search-input" type="search" placeholder="Search customer, reason, notes, or source..." aria-label="Search CRM leads">
                    <button type="button" class="clear-filters-btn" id="crm-clear-filters">Clear Filters</button>
                </div>
            </div>
            <div class="table-wrap">
                <table class="enhanced-table">
                    <thead>
                        <tr>
                            <th>Customer</th>
                            <th>Reason</th>
                            <th>Status</th>
                            <th>Priority</th>
                            <th>Assigned</th>
                            <th>Follow-up</th>
                            <th>Action</th>
                        </tr>
                    </thead>
                    <tbody id="crm-leads-body">
                        <tr>
                            <td colspan="7">
                                <div class="empty-state">
                                    <strong>Loading CRM leads...</strong>
                                    <span>Checking customer follow-up records.</span>
                                </div>
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>
    </main>
'''

content = content[:main_start] + new_html + content[main_end:]
print("HTML replaced")

# ===== 3. Update renderCrmTable class names =====
replaces = [
    ('className = "save-btn"', 'className = "icon-btn"'),
    ('className = "details-btn"', 'className = "icon-btn"'),
    ('className = "save-feedback"', 'className = "save-feedback-inline"'),
    ('className = "action-stack"', 'className = "row-actions"'),
    ('className = "follow-up-cell-stack"', 'className = "follow-up-cell"'),
]
for old, new in replaces:
    count = content.count(old)
    if count > 0:
        content = content.replace(old, new)
        print(f"Replaced '{old}' x{count}")

# Replace func names to enhanced versions
func_replaces = [
    ('createStatusSelect(', 'createEnhancedStatusSelect('),
    ('createAssignedToInput(', 'createEnhancedAssignedToInput('),
    ('createFollowUpDateInput(', 'createEnhancedFollowUpDateInput('),
]
for old, new in func_replaces:
    count = content.count(old)
    if count > 0:
        content = content.replace(old, new)
        print(f"Replaced '{old}' x{count}")

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print(f"Done. New size: {len(content)} chars")
