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
        () => { render({ focus: 'library' }); H.refreshRail && H.refreshRail(); }),
      isolatedRow());
  }

  // Folders kept apart: they play when chosen, never in mixes, sets or the radio.
  function isolatedRow() {
    const kept = H.settings.isolated_folders || [];
    const list = h('div', { class: 'roots' });
    kept.forEach((r, i) => {
      list.appendChild(h('div', { class: 'root-item' }, icon('folder-lock', 'icon-sm'), h('span', { class: 'path', title: r }, r),
        h('button', { class: 'icon-btn', type: 'button', 'aria-label': `להחזיר את ${r} לערבובים`, onclick: async () => {
          if (await save({ isolated_folders: kept.filter((_, j) => j !== i) })) render({ focus: 'library' });
        } }, icon('x', 'icon-sm'))));
    });
    const add = h('button', { class: 'btn btn-outline btn-sm', type: 'button', onclick: async () => {
      const dir = await api.chooseFolder('תיקייה שלא תתנגן בערבובים');
      if (!dir || kept.includes(dir)) return;
      if (await save({ isolated_folders: [...kept, dir] })) render({ focus: 'library' });
    } }, icon('folder-lock', 'icon-sm'), 'הוספת תיקייה');
    return row('תיקיות בנפרד',
      'למשל שירי ילדים או הקלטות של המשפחה: הם בספרייה ומתנגנים כשבוחרים אותם, אבל לא נכנסים לערבובים, לסטים ולרדיו. הקלטות דיבור ושיעורים מופרדות כך מעצמן.',
      add, kept.length ? { wide: list } : {});
  }

  // 1.5: a list of singers the listener brings (CSV, text or JSON).
  function singersRow(st) {
    const count = (st && st.count) || 0;
    const line = h('div', { class: 'set-help' }, count
      ? `בשימוש: ${H.n(count)} זמרים מהרשימה „${st.source || ''}”.` : '');
    const pick = h('button', { class: 'btn btn-outline btn-sm', type: 'button', onclick: async () => {
      const file = await api.chooseFile('רשימת זמרים (CSV, טקסט או JSON)', 'singers');
      if (!file) return;
      const r = await api.importSingers(file, true).catch((err) => ({ ok: false, message: err.message }));
      if (!r.ok) { line.textContent = r.message || 'הרשימה לא נטענה'; return; }
      H.toast(`נטענה רשימה של ${H.n(r.count)} זמרים`, { icon: 'users' });
      api.emit('library-changed', {});
      render({ focus: 'artists' });
    } }, icon('upload', 'icon-sm'), count ? 'רשימה אחרת…' : 'לטעון רשימה…');
    const clear = count ? h('button', { class: 'btn btn-quiet btn-sm', type: 'button', onclick: async () => {
      await api.clearSingers().catch(() => {});
      api.emit('library-changed', {});
      render({ focus: 'artists' });
    } }, 'להסיר') : null;
    return row('רשימת זמרים משלכם',
      'קובץ שבכל שורה בו השם שיוצג ואחריו כתיבים נוספים של אותו זמר, מופרדים בפסיק (למשל: „ישי ריבו,Ishay Ribo,ישי ריבוא”). אפשר גם JSON. הרשימה משלימה את זו של המנגן, וכשהיא קובעת שם אחר — היא קובעת.',
      h('div', { class: 'set-buttons' }, pick, clear), { wide: line });
  }

  // 1.5: the corrections into the files themselves, for MP3 players and phones.
  let tagsRunning = false;
  let tagsLine = null;
  function tagsRow() {
    tagsLine = h('div', { class: 'set-help' }, tagsRunning ? 'כותב…' : '');
    const button = h('button', { class: 'btn btn-outline btn-sm', type: 'button', disabled: tagsRunning, onclick: async () => {
      const r = await api.writeAllTags().catch((err) => ({ started: false, reason: err.message }));
      if (r.started) {
        tagsRunning = true;
        button.disabled = true;
        tagsLine.textContent = 'כותב את הפרטים לקבצים…';
      } else {
        tagsLine.textContent = r.reason === 'already running' ? 'כבר כותב.' : `לא התחיל: ${r.reason || ''}`;
      }
    } }, icon('file-pen-line', 'icon-sm'), 'לכתוב לכל הקבצים');
    return row('לכתוב את התיקונים לקבצים',
      'השם המאוחד של הזמר, שם השיר שתוקן ותמונה (לקבצים שאין להם) — לתוך הקבצים עצמם, כדי שגם נגן MP3, טלפון או תוכנה אחרת יציגו אותם. רק מה ששונה נכתב. קבצים של MP3, M4A, FLAC, OGG ו-WMA.',
      button, { wide: tagsLine });
  }
  api.on('tags_progress', (p) => {
    tagsRunning = true;
    if (tagsLine) tagsLine.textContent = `עבר על ${H.n(p.done)} מתוך ${H.n(p.total)} · נכתבו ${H.n(p.written)}`;
  });
  api.on('tags_done', (r) => {
    tagsRunning = false;
    const text = r && r.error ? `הכתיבה נכשלה: ${r.error}`
      : `הסתיים: נכתבו ${H.songs((r && r.written) || 0)}${r && r.unchanged ? ` · ב-${H.songs(r.unchanged)} הפרטים כבר היו נכונים` : ''}${
        r && r.failed_count ? ` · ${H.songs(r.failed_count)} לא נכתבו (קבצים מוגנים או פגומים)` : ''}`;
    if (tagsLine) tagsLine.textContent = text;
    H.toast(text, { icon: 'file-pen-line' });
    if (!root.hidden) render({ focus: 'artists' });
  });

  // One singer, one name: spellings unified by themselves, and suggestions.
  function artistsGroup(data, singersSt) {
    const groups = (data && data.groups) || [];
    const section = h('section', { class: 'set-group', id: 'set-artists' }, h('h2', {}, 'שמות של זמרים'));
    const choose = async (key, choice) => {
      try {
        await api.setArtistChoice(key, choice);
        render({ focus: 'artists' });
        api.emit('library-changed', {});
      } catch (err) {
        H.toast(`לא הצלחתי לשמור: ${err.message}`, { kind: 'bad' });
      }
    };
    const spellings = (g) => g.variants.map((v) => `${v.name} (${H.n(v.count)})`).join(' · ');
    const waiting = groups.filter((g) => !g.applied && !g.sure);
    const unified = groups.filter((g) => g.applied);
    const apart = groups.filter((g) => !g.applied && g.sure);
    section.append(h('p', { class: 'set-help' },
      'אותו זמר כתוב לפעמים בכמה צורות: בעברית ובאנגלית, עם נקודה או בלי, בכתיב מלא או חסר. המנגן מציג אותו בשם אחד, והחיפוש מוצא את השירים בכל הכתיבים. בקבצים עצמם לא משתנה כלום — אלא אם תבחרו לכתוב את התיקונים לקבצים (למטה).'));
    section.append(singersRow(singersSt), tagsRow());
    if (!groups.length) {
      section.append(h('p', { class: 'muted' }, 'לא נמצאו זמרים שכתובים בכמה צורות.'));
      return section;
    }
    for (const g of waiting) {
      section.append(h('div', { class: 'artist-row waiting' },
        h('div', { class: 'artist-names' }, h('div', { class: 'set-label' }, `אותו זמר? ${g.name}`), h('div', { class: 'set-help' }, spellings(g))),
        h('div', { class: 'artist-actions' },
          h('button', { class: 'btn btn-outline btn-sm', type: 'button', onclick: () => choose(g.key, { merge: true }) }, icon('check', 'icon-sm'), 'לאחד'),
          h('button', { class: 'btn btn-quiet btn-sm', type: 'button', onclick: () => choose(g.key, { apart: true }) }, 'זמרים שונים'))));
    }
    const row = (g) => {
      const pick = h('select', { class: 'select', 'aria-label': `השם של ${g.name}` },
        [...new Set([g.name, ...g.variants.map((v) => v.name)])].map((n) => h('option', { value: n, selected: n === g.name }, n)));
      pick.addEventListener('change', () => choose(g.key, { name: pick.value }));
      return h('div', { class: 'artist-row' },
        h('div', { class: 'artist-names' }, h('div', { class: 'set-label' }, g.name), h('div', { class: 'set-help' }, spellings(g))),
        h('div', { class: 'artist-actions' }, g.applied ? pick : null,
          g.applied
            ? h('button', { class: 'btn btn-quiet btn-sm', type: 'button', onclick: () => choose(g.key, { apart: true }) }, 'לא לאחד')
            : h('button', { class: 'btn btn-quiet btn-sm', type: 'button', onclick: () => choose(g.key, { apart: false, merge: !g.sure }) }, icon('undo-2', 'icon-sm'), 'לאחד שוב')));
    };
    if (unified.length || apart.length) {
      section.append(h('details', { class: 'artist-list', open: !waiting.length && unified.length <= 6 },
        h('summary', {}, `${H.n(unified.length)} זמרים מאוחדים${apart.length ? ` · ${H.n(apart.length)} בנפרד` : ''}`),
        ...unified.map(row), ...apart.map(row)));
    }
    return section;
  }

  function voiceGroup(st) {
    const s = st || {};
    const state = s.available
      ? h('span', { class: 'pill good' }, icon('circle-check'), s.bundled ? 'מוכן (בתוך התוכנה)' : 'מוכן')
      : h('button', { class: 'btn btn-outline btn-sm', type: 'button', onclick: () => { H.go('home'); H.voice.toggle(); } },
        icon('cloud-download', 'icon-sm'), `להוריד (${H.n(s.download_mb || 73)}MB)`);
    return h('section', { class: 'set-group', id: 'set-voice' },
      h('h2', {}, 'בקשה בקול'),
      row('זיהוי דיבור בעברית',
        'לוחצים על המיקרופון שליד שורת הבקשה (או Ctrl+M), אומרים מה לשמוע, והמנגן מבין לבד מתי סיימת. הזיהוי נעשה במחשב, גם בלי אינטרנט, וההקלטה לא נשמרת ולא נשלחת לשום מקום.',
        state),
      h('p', { class: 'set-help credit' }, `המודל: ${s.credit || 'ivrit.ai'}.`));
  }

  function sound() {
    return h('section', { class: 'set-group', id: 'set-sound' },
      h('h2', {}, 'צליל'),
      toggle('normalize_volume', 'עוצמה אחידה',
        'שירים שהוקלטו חזק מתנגנים מעט בשקט, כך שלא צריך לגעת בווליום בין שיר לשיר. המנגן רק מנמיך, אף פעם לא מגביר, כדי שלא יהיה עיוות. לפי ההקשבה ברקע.',
        (on) => H.player.setSoundOptions({ normalize: on })),
      toggle('skip_silence', 'לדלג על שקט בתחילת השיר ובסופו',
        'שקט של יותר משנייה לפני שהשיר מתחיל, או אחרי שנגמר, לא מתנגן. השיר הבא מתחיל מיד.',
        (on) => H.player.setSoundOptions({ skipSilence: on })));
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
      toggle('rhythm_analysis', 'להקשיב גם לקצב ולאנרגיה של כל שיר',
        'בשביל „סט לשמחה” וסטים לאירועים: הסט מתחמם, מגיע לשיא ונרגע, ושירים סמוכים קרובים בקצב. באותה הקשבה, בלי אינטרנט.'),
      row('מעבר רך בין שירים', 'השיר הבא נכנס בהדרגה בזמן שהקודם נחלש. בסטים יש תמיד מעבר רך של 6 שניות לפחות.',
        segmented([['0', 'כבוי'], ['3', '3 שניות'], ['6', '6 שניות'], ['10', '10 שניות']], String(H.settings.crossfade_seconds || 0),
          async (v) => { if (await save({ crossfade_seconds: Number(v) })) H.player.setCrossfade(Number(v)); }, 'מעבר רך')),
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

  // Details and covers for the whole library, filled in only for a sure match.
  let detailsRunning = false;
  let detailsLine = null;
  function detailsRow() {
    detailsLine = h('div', { class: 'set-help' }, detailsRunning ? 'מחפש פרטים…' : '');
    const button = h('button', { class: 'btn btn-outline btn-sm', type: 'button', onclick: async () => {
      if (detailsRunning) {
        await api.stopCompleteDetails().catch(() => {});
        detailsLine.textContent = 'נעצר אחרי השיר הנוכחי.';
        return;
      }
      const r = await api.completeDetails().catch((err) => ({ started: false, reason: err.message }));
      if (r.started) {
        detailsRunning = true;
        button.textContent = 'לעצור';
        detailsLine.textContent = 'מחפש פרטים ותמונות ברשת…';
      } else {
        detailsLine.textContent = r.reason === 'already running' ? 'כבר מחפש.' : `לא התחיל: ${r.reason || ''}`;
      }
    } }, icon('image', 'icon-sm'), detailsRunning ? 'לעצור' : 'להשלים');
    return row('פרטים ותמונות לכל הספרייה',
      'לשירים בלי תמונה או בלי זמר: המנגן מחפש ברשת, וממלא רק כשההתאמה ודאית — אותו שם, אותו זמר ואותו אורך. השאר נשאר לבחירה מהתפריט של השיר („פרטים ותמונה מהרשת”). הקבצים עצמם לא משתנים. איטי בכוונה, ברקע.',
      button, { wide: detailsLine });
  }
  api.on('details_progress', (p) => {
    detailsRunning = true;
    if (detailsLine) detailsLine.textContent = `עבר על ${H.n(p.done)} מתוך ${H.n(p.total)} שירים · נמצאו פרטים ל-${H.n(p.found)}`;
  });
  api.on('details_done', (r) => {
    detailsRunning = false;
    const text = r && r.message ? r.message
      : r && r.total === 0 ? 'אין שירים שחסרים להם פרטים (או שכבר חיפשתי אותם).'
        : `הסתיים: נמצאו פרטים ותמונה ל-${H.n((r && r.found) || 0)} מתוך ${H.n((r && r.done) || 0)} שירים.`;
    if (detailsLine) detailsLine.textContent = text;
    H.toast(text, { icon: 'image' });
    if (!root.hidden) render({ focus: 'online' });
  });

  function online(info) {
    const folder = (info && info.downloads_dir) || '';
    return h('section', { class: 'set-group', id: 'set-online' },
      h('h2', {}, 'השלמה מהרשת'),
      toggle('autoplay_after_download', 'לנגן שיר מיד כשההורדה מסתיימת', null),
      detailsRow(),
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
            const smart = r.app.smart || {};
            result.append(h('div', {}, `גרסה ${r.app.latest} זמינה (מותקנת ${r.app.current}). `,
              smart.possible
                ? h('button', { class: 'btn btn-primary btn-sm', type: 'button', onclick: () => H.startAppUpdate(r.app) },
                  `לעדכן עכשיו (${smart.download_text})`)
                : h('button', { class: 'btn btn-quiet btn-sm', type: 'button', onclick: () => api.openExternal(r.app.url) }, 'להורדה')));
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
      toggle('auto_update', 'לבדוק עדכונים בכל הפעלה', 'רק בדיקה: התוכנה לא מתעדכנת לבד בלי לשאול. כשמעדכנים, יורדים רק החלקים שהשתנו — בדרך כלל כמה מגה-בייט, והמודל לא יורד שוב.'),
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
    const [settings, status, overview, info, shell, vocal, artistData, voiceSt, , singersSt] = await Promise.all([
      api.getSettings(), api.classifierStatus().catch(() => null), api.overview().catch(() => null),
      api.appInfo().catch(() => null), api.shellInfo(), api.vocalStatus().catch(() => null),
      api.artistGroups().catch(() => null), api.voiceStatus().catch(() => null),
      H.shabbat ? H.shabbat.refresh() : null, api.singersStatus().catch(() => null),
    ]);
    H.settings = settings;
    H.appInfo = info;
    H.clear(root).append(
      h('header', { class: 'page-head' }, h('h1', {}, 'הגדרות')),
      h('div', { class: 'settings' },
        appearance(), library(overview), artistsGroup(artistData, singersSt), sound(), voiceGroup(voiceSt), ai(status, info), suggestions(), shabbat(), listening(vocal), online(info), updates(info),
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
