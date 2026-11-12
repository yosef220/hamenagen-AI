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
      toggle('include_video', 'לכלול קובצי וידאו', 'קבצי MP4 ודומיהם יופיעו בספרייה ויתנגנו כשמע.', () => H.rescan()),
      toggle('hide_duplicates', 'להציג כל שיר פעם אחת',
        stats && stats.duplicates
          ? `${H.n(stats.duplicates)} עותקים של שירים שכבר יש (בתיקייה אחרת או בפורמט אחר) מוסתרים, ומוצג העותק הטוב ביותר. את העותקים רואים בתפריט ⋯ של השיר.`
          : 'שיר שנמצא בכמה תיקיות או בכמה פורמטים יוצג פעם אחת, בעותק הטוב ביותר.',
        () => { render({ focus: 'library' }); H.refreshRail && H.refreshRail(); }));
  }

  function modelPill(st) {
    if (!st || !st.enabled) return h('span', { class: 'pill' }, 'כבוי — מילון בלבד');
    if (st.loaded || st.available) return h('span', { class: 'pill good' }, icon('circle-check'), 'פעיל');
    if (modelState === 'downloading' || modelState === 'loading') return h('span', { class: 'pill warn' }, icon('loader-circle', 'spin'), modelState === 'loading' ? 'נטען' : 'מוריד');
    if (st.cached) return h('span', { class: 'pill' }, 'מותקן, ייטען כשיידרש');
    return h('span', { class: 'pill warn' }, 'לא מותקן');
  }

  function knowledgeRow(info) {
    const k = info && info.knowledge;
    if (!k || !k.songs) return null;
    const built = k.version ? ` · נבנה ב-${k.version.split('-').reverse().join('.')}` : '';
    return row('אינדקס הידע',
      `${H.n(k.songs)} שירים ופיוטים לפי מועד, ואוצר מילים ל-${H.n(k.topics)} מועדים מ-${H.n(k.sources)} מקורות — ויקיפדיה העברית וספריא${built}. נמצא בתוך התוכנה ועובד בלי אינטרנט.`,
      h('span', { class: 'pill good' }, icon('book-open'), 'פעיל'));
  }

  function ai(status, info) {
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
      knowledgeRow(info),
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

  // ------------------------------------------------------------ listening for vocal songs
  let vocalLine = null;

  function vocalSummary(v) {
    if (!v) return '';
    if (!v.available) {
      return !v.model_found ? 'רכיב הזיהוי לא נמצא בגרסה הזו של התוכנה.' : 'ספריית פענוח השמע חסרה בגרסה הזו.';
    }
    const parts = [`נבדקו ${H.n(v.analyzed)} מתוך ${H.songs(v.total)}`];
    if (v.vocal || v.maybe) parts.push(`נשמעו ווקאליים: ${H.n(v.vocal)}${v.maybe ? `, ועוד ${H.n(v.maybe)} אולי` : ''}`);
    if (v.unreadable) parts.push(`${H.n(v.unreadable)} בפורמט שלא נבדק (M4A, WMA)`);
    return parts.join(' · ');
  }

  function listening(v) {
    const st = v || {};
    const run = h('button', { class: 'btn btn-outline btn-sm', type: 'button', disabled: !st.available || !H.settings.vocal_detection, onclick: async () => {
      if (st.running) { await api.stopVocal().catch(() => {}); H.toast('הבדיקה תיעצר אחרי השיר הנוכחי', { icon: 'ear' }); return; }
      const r = await api.analyzeVocal().catch((err) => ({ started: false, reason: err.message }));
      H.toast(r.started ? 'הבדיקה רצה ברקע. אפשר להמשיך להאזין.' : 'אין כרגע שירים חדשים לבדוק', { icon: 'ear' });
    } }, icon(st.running ? 'x' : 'ear', 'icon-sm'), st.running ? 'לעצור' : 'לבדוק עכשיו');
    const review = st.to_review
      ? h('button', { class: 'btn btn-quiet btn-sm', type: 'button', onclick: () => H.openTopic('ווקאלי') },
        `${H.songs(st.to_review)} ממתינים לאישור`)
      : null;
    vocalLine = h('div', { class: 'set-help num' }, vocalSummary(st));
    return h('section', { class: 'set-group', id: 'set-vocal' },
      h('h2', {}, 'זיהוי שירים ווקאליים'),
      toggle('vocal_detection', 'להקשיב לשירים ולזהות שירה בלי כלי נגינה',
        'המנגן מקשיב לשלושה קטעים קצרים מכל שיר (כחמישית שנייה לשיר), ברקע ובלי אינטרנט. המודל קטן ונמצא בתוך התוכנה.',
        () => render({ focus: 'vocal' })),
      row('המצב', null, h('div', { style: { display: 'flex', gap: '8px', 'align-items': 'center' } }, review, run), { wide: vocalLine }),
      toggle('vocal_auto_include', 'לצרף מיד שירים שזוהו בוודאות',
        'כבוי: שירים שזוהו מחכים לאישור שלך בעמוד „ווקאלי”, ורק שירים שאושרו מוצעים בימי הספירה ובין המצרים. הזיהוי אוטומטי ויכול לטעות — בעיקר בשירה עם ליווי חלש מאוד.'));
  }

  function shabbat() {
    const s = H.settings;
    const st = H.shabbat ? H.shabbat.status() : null;
    const cities = (st && st.cities) || [s.shabbat_city];
    const line = h('div', { class: 'set-times' });
    const describe = (r) => {
      if (!r || !r.enabled) return 'מצב השבת כבוי.';
      const w = r.current || r.next;
      if (!w) return '';
      const what = w.kind === 'shabbat' ? (w.detail || 'שבת') : w.title;
      return `${what}: הדלקת נרות ב${w.eve_weekday} ${w.candle_text}, המוזיקה נעצרת ${w.stop_text}, ${w.end_label} ${w.end_text}. מקור הזמנים: ${w.source_label}.`;
    };
    const refreshLine = async () => { line.textContent = describe(await H.shabbat.refresh()); };
    refreshLine();
    const select = (key, label, options, value, numeric) => {
      const el = h('select', { class: 'select', 'aria-label': label },
        options.map(([v, text]) => h('option', { value: String(v), selected: String(v) === String(value) }, text)));
      el.addEventListener('change', async () => {
        if (await save({ [key]: numeric ? Number(el.value) : el.value })) {
          if (key === 'shabbat_city') render({ focus: 'shabbat' });
          else refreshLine();
        }
      });
      return el;
    };
    const cityMinutes = st ? st.city_minutes : 18;
    return h('section', { class: 'set-group', id: 'set-shabbat' },
      h('h2', {}, 'שבת וחג'),
      toggle('shabbat_mode', 'מצב שבת וחג',
        'לפני הדלקת נרות המוזיקה נחלשת ונעצרת, ועד צאת השבת או החג מוצג „שבת שלום” ושום דבר לא מתנגן. הזמנים מאתר זמנים טובא (כתר תורה); אם אין אליו גישה — מ-Hebcal, ובלי אינטרנט בכלל — מחישוב במחשב.',
        () => refreshLine()),
      row('העיר', null, select('shabbat_city', 'העיר', cities.map((c) => [c, c]), s.shabbat_city)),
      row('הדלקת נרות', 'כמה דקות לפני השקיעה',
        select('candle_minutes', 'הדלקת נרות', [[0, `כמנהג העיר (${cityMinutes} דקות)`], [18, '18 דקות'], [20, '20 דקות'], [22, '22 דקות'], [30, '30 דקות'], [40, '40 דקות']], s.candle_minutes, true)),
      row('עצירת המוזיקה', 'כמה זמן לפני הדלקת נרות',
        select('shabbat_stop_before', 'עצירת המוזיקה', [[0, 'בזמן הדלקת נרות'], [5, '5 דקות לפני'], [10, '10 דקות לפני'], [15, '15 דקות לפני'], [20, '20 דקות לפני'], [30, 'חצי שעה לפני']], s.shabbat_stop_before, true)),
      row('צאת השבת', null,
        segmented([['tzeit', 'צאת הכוכבים'], ['rt', 'רבנו תם']], s.havdalah, async (v) => { if (await save({ havdalah: v })) refreshLine(); }, 'צאת השבת'),
        { wide: line }),
      row('המסך בשבת', 'כך ייראה המנגן מהדלקת נרות ועד צאת השבת.',
        h('button', { class: 'btn btn-outline btn-sm', type: 'button', onclick: () => {
          const r = H.shabbat.status();
          H.shabbat.preview(r && (r.current || r.next));
        } }, icon('eye', 'icon-sm'), 'להציג')));
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
    const build = window.__BUILD__ && window.__BUILD__.build !== 'dev' ? ` · ${window.__BUILD__.build}` : '';
    add('גרסה', `${shell.version} · ${shell.editionLabel}${build}`);
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
    const [settings, status, overview, info, shell, vocal] = await Promise.all([
      api.getSettings(), api.classifierStatus().catch(() => null), api.overview().catch(() => null),
      api.appInfo().catch(() => null), api.shellInfo(), api.vocalStatus().catch(() => null),
      H.shabbat ? H.shabbat.refresh() : null,
    ]);
    H.settings = settings;
    H.appInfo = info;
    H.clear(root).append(
      h('header', { class: 'page-head' }, h('h1', {}, 'הגדרות')),
      h('div', { class: 'settings' },
        appearance(), library(overview), ai(status, info), suggestions(), shabbat(), listening(vocal), online(info), updates(info),
        about(info, shell)));
    if (params.focus) {
      const target = H.$(`#set-${params.focus}`);
      if (target) target.scrollIntoView({ block: 'start' });
    }
  }

  api.on('model_install', (msg) => {
    modelState = msg.status === 'done' || msg.status === 'error' ? null : msg.status;
    if (!root.hidden) render();
  });
  api.on('vocal_progress', (msg) => {
    if (!root.hidden && vocalLine) vocalLine.textContent = `מקשיב… ${H.n(msg.done)} מתוך ${H.n(msg.total)} שירים חדשים`;
  });
  api.on('vocal_done', () => { if (!root.hidden) render({ focus: null }); });

  H.views = H.views || {};
  H.views.settings = { show: render };
})();
