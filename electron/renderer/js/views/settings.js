'use strict';

/* Settings: appearance, library folders, the AI model, suggestions, downloads, updates, about. */
(function () {
  const { h, icon, api } = H;
  const root = H.$('#view-settings');
  let modelState = null;

  async function save(values) {
    try {
      H.settings = await api.updateSettings(values);
      return H.settings;
    } catch (err) {
      H.toast(`לא הצלחתי לשמור: ${err.message}`, { kind: 'bad' });
      return null;
    }
  }

  // ------------------------------------------------------------ controls
  function row(label, help, control, opts = {}) {
    return h('div', { class: 'set-row', id: opts.id || null },
      h('div', {}, h('div', { class: 'set-label' }, label), help ? h('div', { class: 'set-help' }, help) : null),
      control ? h('div', { class: 'set-control' }, control) : null,
      opts.wide ? h('div', { class: 'set-wide' }, opts.wide) : null);
  }

  function toggle(key, label, help, after) {
    const input = h('input', { class: 'switch', type: 'checkbox', role: 'switch', 'aria-label': label, checked: !!H.settings[key] });
    input.addEventListener('change', async () => {
      const s = await save({ [key]: input.checked });
      if (s && after) after(input.checked);
    });
    return row(label, help, input);
  }

  function segmented(options, value, onPick, label) {
    const group = h('div', { class: 'segmented', role: 'group', 'aria-label': label });
    for (const [key, text, ic] of options) {
      group.appendChild(h('button', {
        type: 'button',
        'aria-pressed': key === value ? 'true' : 'false',
        onclick: () => {
          for (const b of group.children) b.setAttribute('aria-pressed', 'false');
          group.querySelector(`[data-key="${key}"]`).setAttribute('aria-pressed', 'true');
          onPick(key);
        },
        'data-key': key,
      }, ic ? icon(ic) : null, text));
    }
    return group;
  }

  // ------------------------------------------------------------ groups
  function appearance() {
    const s = H.settings;
    return h('section', { class: 'set-group', id: 'set-appearance' },
      h('h2', {}, 'מראה'),
      row('ערכת צבעים', 'בהירה כמו מפה לבנה של שבת, או כהה כמו קטיפה של מעיל ספר תורה.',
        segmented([['light', 'בהיר', 'sun'], ['dark', 'כהה', 'moon'], ['system', 'כמו ב-Windows', 'monitor']], s.theme,
          async (v) => { H.applyTheme(v); await save({ theme: v }); }, 'ערכת צבעים')),
      row('גודל הטקסט', 'מגדיל את כל הכתב והכפתורים יחד.',
        segmented([['normal', 'רגיל'], ['large', 'גדול'], ['xlarge', 'גדול מאוד']], s.text_size,
          async (v) => { H.applyTextSize(v); await save({ text_size: v }); }, 'גודל הטקסט')));
  }

  function library(overview) {
    const s = H.settings;
    const roots = s.scan_roots || [];
    const list = h('div', { class: 'roots' });
    if (!roots.length) {
      list.appendChild(h('div', { class: 'root-item' }, icon('hard-drive-download', 'icon-sm'),
        h('span', { style: { flex: '1' } }, 'כל המחשב — תיקיית המשתמש וכל הכוננים הנוספים')));
    }
    roots.forEach((r, i) => {
      list.appendChild(h('div', { class: 'root-item' }, icon('folder-open', 'icon-sm'), h('span', { class: 'path', title: r }, r),
        h('button', { class: 'icon-btn', type: 'button', 'aria-label': `להסיר את ${r}`, onclick: async () => {
          const next = roots.filter((_, j) => j !== i);
          if (await save({ scan_roots: next })) { render(); H.rescan(); }
        } }, icon('x', 'icon-sm'))));
    });
    const addBtn = h('button', { class: 'btn btn-outline btn-sm', type: 'button', onclick: async () => {
      const dir = await api.chooseFolder('בחירת תיקיית מוזיקה');
      if (!dir || roots.includes(dir)) return;
      if (await save({ scan_roots: [...roots, dir] })) { render(); H.rescan(); }
    } }, icon('folder-plus', 'icon-sm'), 'הוספת תיקייה');
    const allBtn = roots.length
      ? h('button', { class: 'btn btn-quiet btn-sm', type: 'button', onclick: async () => {
        if (await save({ scan_roots: [] })) { render(); H.rescan(); }
      } }, 'לחזור לכל המחשב')
      : null;

    const stats = overview ? overview.stats : null;
    const last = overview && overview.last_scan_at ? `נסרק ${H.ago(overview.last_scan_at)}` : 'עוד לא נסרק';
    return h('section', { class: 'set-group', id: 'set-library' },
      h('h2', {}, 'הספרייה'),
      row('תיקיות לסריקה', 'המנגן סורק ברקע בכל הפעלה. קבצים שלא השתנו לא נקראים שוב, כך שהסריקה מהירה.',
        h('div', { style: { display: 'flex', gap: '8px' } }, allBtn, addBtn), { wide: list }),
      row('לסרוק עכשיו', `${stats ? `${H.songs(stats.tracks)} · ` : ''}${last}`,
        h('button', { class: 'btn btn-outline btn-sm', type: 'button', onclick: () => H.rescan(true) }, icon('refresh-cw', 'icon-sm'), 'לסרוק')),
      toggle('include_video', 'לכלול קובצי וידאו', 'קבצי MP4 ודומיהם יופיעו בספרייה ויתנגנו כשמע.', () => H.rescan()));
  }

  function modelPill(st) {
    if (!st || !st.enabled) return h('span', { class: 'pill' }, 'כבוי — מילון בלבד');
    if (st.loaded || st.available) return h('span', { class: 'pill good' }, icon('circle-check'), 'פעיל');
    if (modelState === 'downloading' || modelState === 'loading') return h('span', { class: 'pill warn' }, icon('loader-circle', 'spin'), modelState === 'loading' ? 'נטען' : 'מוריד');
    if (st.cached) return h('span', { class: 'pill' }, 'מותקן, ייטען כשיידרש');
    return h('span', { class: 'pill warn' }, 'לא מותקן');
  }

  function ai(status) {
    const st = status || {};
    const where = st.bundled ? 'המודל מגיע בתוך התוכנה (גרסה מלאה לאופליין).' : 'המודל ירד פעם אחת כשיש אינטרנט, ומאז עובד בלי רשת.';
    const install = st.enabled && !st.loaded && !st.available
      ? h('button', { class: 'btn btn-outline btn-sm', type: 'button', onclick: async () => {
        modelState = 'downloading';
        render();
        try { await api.installModel(); } catch (err) { H.toast(err.message, { kind: 'bad' }); }
      } }, icon('download', 'icon-sm'), 'להתקין עכשיו')
      : null;
    return h('section', { class: 'set-group', id: 'set-ai' },
      h('h2', {}, 'בינה מלאכותית מקומית'),
      row('מודל הסיווג', `${where} ${st.model ? `(${st.model.split('/').pop()})` : ''}`, h('div', { style: { display: 'flex', gap: '8px', 'align-items': 'center' } }, modelPill(st), install)),
      toggle('use_embeddings', 'סיווג חכם לשירים בלי מילת מפתח', 'כשהשם של שיר לא מגלה את הנושא, המודל משווה את המשמעות שלו לנושאים. כבוי = מילון בלבד.', () => render()),
      toggle('classify_by_lyrics', 'להיעזר בקובצי מילים', 'אם ליד שיר יש קובץ ‎.lrc או ‎.txt, גם המילים נלקחות בחשבון.'),
      row('לסווג מחדש', 'מריץ את הסיווג על כל השירים — למשל אחרי שהמודל הותקן.',
        h('button', { class: 'btn btn-outline btn-sm', type: 'button', onclick: async () => {
          try { await api.reclassify(); H.toast('הסיווג מחדש רץ ברקע', { icon: 'cpu' }); } catch (err) { H.toast(err.message, { kind: 'bad' }); }
        } }, icon('cpu', 'icon-sm'), 'לסווג מחדש')));
  }

  function suggestions() {
    return h('section', { class: 'set-group', id: 'set-suggestions' },
      h('h2', {}, 'הצעות לפי הלוח'),
      toggle('vocal_suggestions', 'מוזיקה ווקאלית בימי הספירה ובין המצרים',
        'בימים האלה הלוח בדף הבית מציע שירים ווקאליים (בלי כלים) במקום ההצעה הרגילה. הספירה מוצגת בכל מקרה.',
        () => H.views.home && H.views.home.refresh && H.views.home.refresh()));
  }

  function online(info) {
    const folder = (info && info.downloads_dir) || '';
    return h('section', { class: 'set-group', id: 'set-online' },
      h('h2', {}, 'השלמה מהרשת'),
      toggle('autoplay_after_download', 'לנגן שיר מיד כשההורדה מסתיימת', null),
      row('תיקיית ההורדות', folder || '—',
        h('div', { style: { display: 'flex', gap: '8px' } },
          h('button', { class: 'btn btn-quiet btn-sm', type: 'button', onclick: () => api.openFolder(folder) }, icon('folder-open', 'icon-sm'), 'לפתוח'),
          h('button', { class: 'btn btn-outline btn-sm', type: 'button', onclick: async () => {
            const dir = await api.chooseFolder('בחירת תיקיית הורדות');
            if (dir && await save({ downloads_dir: dir })) { H.appInfo = await api.appInfo(); render(); }
          } }, 'לשנות'))),
      row('רכיב ההורדה (yt-dlp)', info && info.ytdlp ? `גרסה ${info.ytdlp}. מתעדכן אוטומטית יחד עם שאר העדכונים.` : 'לא מותקן בגרסה הזו.', null));
  }

  function updates(info) {
    const result = h('div', { class: 'set-help', id: 'update-result' });
    const check = h('button', { class: 'btn btn-outline btn-sm', type: 'button', onclick: async () => {
      check.disabled = true;
      result.textContent = 'בודק…';
      try {
        const r = await api.checkUpdates(true);
        H.clear(result);
        if (!r.online) {
          result.textContent = 'לא ניתן לבדוק עכשיו — אין חיבור לרשת.';
        } else {
          if (r.app && r.app.newer) {
            result.append(h('div', {}, `גרסה ${r.app.latest} זמינה (מותקנת ${r.app.current}). `,
              h('button', { class: 'btn btn-quiet btn-sm', type: 'button', onclick: () => api.openExternal(r.app.url) }, 'להורדה')));
          } else {
            result.append(h('div', {}, `המנגן מעודכן (גרסה ${info ? info.version : ''}).`));
          }
          for (const u of r.updates.filter((x) => x.action === 'auto')) {
            const label = u.component === 'ytdlp' ? 'רכיב ההורדה' : 'מילון הנושאים';
            const line = h('div', {}, `${label}: גרסה ${u.latest} זמינה. `);
            line.append(h('button', { class: 'btn btn-quiet btn-sm', type: 'button', onclick: async (e) => {
              e.target.disabled = true;
              const ap = await api.applyUpdate(u.component, u.url, u.latest).catch((err) => ({ ok: false, message: err.message }));
              line.textContent = ap.ok ? `${label} עודכן.` : `העדכון נכשל: ${ap.message}`;
            } }, 'לעדכן'));
            result.append(line);
          }
        }
      } catch (err) {
        result.textContent = err.message;
      }
      check.disabled = false;
    } }, icon('refresh-cw', 'icon-sm'), 'לבדוק עכשיו');

    const packBtn = h('button', { class: 'btn btn-outline btn-sm', type: 'button', onclick: async () => {
      const r = await api.installOfflinePack(null).catch((err) => ({ ok: false, message: err.message }));
      H.toast(r.count ? `הותקנו ${r.count} חבילות אופליין` : (r.message || 'לא נמצאה חבילת אופליין חדשה ליד התוכנה'), { icon: 'package' });
    } }, icon('package', 'icon-sm'), 'לחפש חבילה');

    return h('section', { class: 'set-group', id: 'set-updates' },
      h('h2', {}, 'עדכונים'),
      toggle('auto_update', 'לבדוק עדכונים בכל הפעלה', 'רק בדיקה: התוכנה לא מתעדכנת לבד בלי לשאול.'),
      row('בדיקה ידנית', null, check, { wide: result }),
      row('חבילת אופליין', 'למחשב בלי אינטרנט: מניחים קובץ ‎.pack ליד התוכנה והיא מתקינה ממנו.', packBtn));
  }

  function about(info, shell) {
    const kv = h('dl', { class: 'kv' });
    const add = (k, v) => kv.append(h('dt', {}, k), h('dd', {}, v));
    add('גרסה', `${shell.version} · ${shell.editionLabel}`);
    if (info) {
      add('תיקיית הנתונים', h('span', { class: 'ltr' }, info.data_dir));
      add('מודל הסיווג', h('span', { class: 'ltr' }, info.models_dir));
      add('Python', info.python);
      add('מערכת', info.platform);
    }
    return h('section', { class: 'set-group', id: 'set-about' },
      h('h2', {}, 'אודות'),
      h('div', { class: 'set-row' }, h('div', { class: 'set-wide' }, kv)),
      row('תיקיית הנתונים', 'הספרייה, ההגדרות, השירים שאהבת וההיסטוריה. בגרסה הניידת — ליד התוכנה.',
        h('button', { class: 'btn btn-quiet btn-sm', type: 'button', onclick: () => api.openFolder(shell.dataDir) }, icon('folder-open', 'icon-sm'), 'לפתוח')));
  }

  async function render(params = {}) {
    const [settings, status, overview, info, shell] = await Promise.all([
      api.getSettings(), api.classifierStatus().catch(() => null), api.overview().catch(() => null),
      api.appInfo().catch(() => null), api.shellInfo(),
    ]);
    H.settings = settings;
    H.appInfo = info;
    H.clear(root).append(
      h('header', { class: 'page-head' }, h('h1', {}, 'הגדרות')),
      h('div', { class: 'settings' },
        appearance(), library(overview), ai(status), suggestions(), online(info), updates(info), about(info, shell)));
    if (params.focus) {
      const target = H.$(`#set-${params.focus}`);
      if (target) target.scrollIntoView({ block: 'start' });
    }
  }

  api.on('model_install', (msg) => {
    modelState = msg.status === 'done' || msg.status === 'error' ? null : msg.status;
    if (!root.hidden) render();
  });

  H.views = H.views || {};
  H.views.settings = { show: render };
})();
