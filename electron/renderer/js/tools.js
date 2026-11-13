'use strict';

/*
 * 1.5: what the listener does with songs outside the player.
 *
 *  - H.writeTags(tracks)        the details the player shows, into the files
 *  - H.openExport(tracks, name) copy songs to an MP3 player or a USB stick
 *  - H.openRingtone(track)      cut a ringtone for the phone
 */
(function () {
  const { h, icon, api } = H;

  const mb = (bytes) => {
    const v = (bytes || 0) / (1024 * 1024);
    return v >= 1024 ? `${(v / 1024).toFixed(1)} GB` : `${Math.round(v)} MB`;
  };

  function dialog(id, title, sub) {
    const el = h('dialog', { class: 'dialog dialog-narrow tool-dialog', 'aria-labelledby': `${id}-title` });
    document.body.appendChild(el);
    el.addEventListener('click', (e) => { if (e.target === el && !el.dataset.busy) el.close(); });
    el.addEventListener('cancel', (e) => { if (el.dataset.busy) e.preventDefault(); });
    el.addEventListener('close', () => el.remove());
    const subtitle = h('p', { class: 'muted' }, sub || '');
    const body = h('div', { class: 'dialog-body' });
    const foot = h('footer', { class: 'dialog-foot' });
    el.append(
      h('header', { class: 'dialog-head' },
        h('div', { class: 'dialog-heading' }, h('h2', { id: `${id}-title` }, title), subtitle),
        h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'סגירה', onclick: () => { if (!el.dataset.busy) el.close(); } }, icon('x'))),
      body, foot);
    el.showModal();
    return { el, body, foot, subtitle };
  }

  function choice(label, options, value, onPick) {
    const group = h('div', { class: 'segmented', role: 'group', 'aria-label': label });
    for (const [key, text] of options) {
      group.appendChild(h('button', {
        type: 'button', 'data-key': key, 'aria-pressed': key === value ? 'true' : 'false',
        onclick: () => {
          for (const b of group.children) b.setAttribute('aria-pressed', b.dataset.key === key ? 'true' : 'false');
          onPick(key);
        },
      }, text));
    }
    return h('div', { class: 'tool-row' }, h('div', { class: 'tool-label' }, label), group);
  }

  // ------------------------------------------------------------ details into the files
  H.writeTags = async function writeTags(tracks) {
    const list = (tracks || []).filter((t) => t && t.path && t.source !== 'youtube');
    if (!list.length) return;
    H.closeTrackMenu && H.closeTrackMenu();
    try {
      const r = await api.writeTags(list.map((t) => t.id), true);
      if (r.failed_count) {
        const reason = r.failed[0] && r.failed[0].reason;
        const why = reason === 'read-only' ? 'הקובץ מוגן מפני כתיבה'
          : reason === 'cloud' ? 'הקובץ נמצא רק בענן (OneDrive/Dropbox). נגנו אותו פעם אחת, ואז אפשר לכתוב'
            : reason || '';
        H.toast(`לא הצלחתי לכתוב ל-${H.songs(r.failed_count)}${why ? `: ${why}` : ''}`, { kind: 'bad' });
      } else if (!r.written && r.unchanged) {
        H.toast(list.length === 1 ? 'הפרטים בקובץ כבר נכונים' : 'הפרטים בקבצים כבר נכונים', { icon: 'file-pen-line' });
      } else if (!r.written) {
        H.toast('את הקובץ הזה אי אפשר לעדכן (רק MP3, M4A, FLAC, OGG ו-WMA)', { kind: 'bad' });
      } else {
        H.toast(list.length === 1 ? `הפרטים של „${H.trackTitle(list[0])}” נכתבו לקובץ` : `הפרטים נכתבו ל-${H.songs(r.written)}`, { icon: 'file-pen-line' });
      }
    } catch (err) {
      H.toast(`לא הצלחתי לכתוב: ${err.message}`, { kind: 'bad' });
    }
  };

  // ------------------------------------------------------------ to an MP3 player
  let exporting = null;      // { dialog parts } while a copy runs

  H.openExport = async function openExport(tracks, name, preset = {}) {
    const songs = (tracks || []).filter((t) => t && t.path && t.source !== 'youtube');
    if (!songs.length) {
      H.toast('אין כאן שירים מהמחשב להעתקה', { kind: 'bad' });
      return;
    }
    if (exporting) { exporting.el.showModal && !exporting.el.open && exporting.el.showModal(); return; }
    const d = dialog('export', 'העתקה לנגן MP3', `${H.songs(songs.length)}${name ? ` · ${name}` : ''}`);
    const opts = { dest: '', folder: (name || 'המנגן').slice(0, 60), layout: 'flat', numbered: true, convert: true };
    const drives = h('div', { class: 'drive-list', role: 'radiogroup', 'aria-label': 'לאן להעתיק' });
    const summary = h('p', { class: 'tool-summary', 'aria-live': 'polite' });
    const go = h('button', { class: 'btn btn-primary', type: 'button', disabled: true }, icon('usb', 'icon-sm'), 'להעתיק');
    const folderInput = h('input', { class: 'input', type: 'text', value: opts.folder, 'aria-label': 'שם התיקייה בנגן', maxlength: '80' });
    let info = null;
    let ffmpeg = true;
    const convertBox = h('input', { type: 'checkbox', checked: true, onchange: (e) => { opts.convert = e.target.checked; plan(); } });

    const pickDrive = (path, label) => {
      opts.dest = path;
      for (const b of drives.querySelectorAll('.drive')) b.setAttribute('aria-checked', b.dataset.path === path ? 'true' : 'false');
      if (label && !drives.querySelector(`.drive[data-path="${CSS.escape(path)}"]`)) {
        for (const note of drives.querySelectorAll('p')) note.remove();
        drives.appendChild(driveButton({ path, label, free: null }, true));
      }
      plan();
    };
    const driveButton = (dv, on) => h('button', {
      type: 'button', class: 'drive', role: 'radio', 'data-path': dv.path, 'aria-checked': on ? 'true' : 'false',
      onclick: () => pickDrive(dv.path),
    }, icon(dv.free == null ? 'folder-open' : 'usb', 'icon-sm'),
    h('span', { class: 'drive-name' }, dv.label),
    dv.free == null ? h('span', { class: 'drive-free', dir: 'ltr', title: dv.path }, dv.path)
      : h('span', { class: 'drive-free num' }, `${mb(dv.free)} פנויים`));

    async function loadDrives() {
      drives.replaceChildren(h('p', { class: 'muted dialog-wait' }, icon('loader-circle', 'icon-sm spin'), 'מחפש נגנים ודיסקים מחוברים…'));
      const r = await api.exportDrives().catch(() => ({ drives: [] }));
      ffmpeg = r.ffmpeg !== false;
      if (!ffmpeg) { opts.convert = false; convertBox.checked = false; convertBox.disabled = true; }
      drives.replaceChildren();
      for (const dv of r.drives || []) drives.appendChild(driveButton(dv, dv.path === opts.dest));
      if (!(r.drives || []).length) drives.appendChild(h('p', { class: 'muted' }, 'לא נמצא נגן מחובר. חברו את הנגן או את הדיסק־און־קי, או בחרו תיקייה.'));
      if (preset.dest && !opts.dest) pickDrive(preset.dest, preset.label || preset.dest);
      else if (!opts.dest && (r.drives || []).length === 1) pickDrive(r.drives[0].path);
    }

    const plan = H.debounce(async () => {
      if (!opts.dest) { summary.textContent = 'בחרו לאן להעתיק.'; go.disabled = true; return; }
      summary.textContent = 'בודק כמה מקום יש…';
      go.disabled = true;
      try {
        info = await api.exportPlan({ ...opts, ids: songs.map((t) => t.id) });
      } catch (err) {
        summary.textContent = err.message;
        return;
      }
      const parts = [];
      const fresh = info.count - info.already;
      parts.push(fresh ? `יועתקו ${H.songs(fresh)} (${mb(info.total)})` : 'כל השירים כבר בנגן');
      if (info.already) parts.push(`${H.songs(info.already)} כבר שם`);
      if (info.convert) parts.push(`${H.songs(info.convert)} יומרו ל-MP3`);
      if (info.left_out_count) parts.push(`${H.songs(info.left_out_count)} לא ייכנסו — אין מספיק מקום`);
      const sep = /[\\/]$/.test(info.dest) ? '' : (info.dest.includes('\\') ? '\\' : '/');
      summary.replaceChildren(`${parts.join(' · ')}. לתיקייה: `, h('bdi', { dir: 'ltr' }, `${info.dest}${sep}${info.folder}`));
      go.disabled = !fresh;
    }, 250);

    folderInput.addEventListener('input', () => { opts.folder = folderInput.value.trim() || 'המנגן'; plan(); });
    const chooseFolder = h('button', { class: 'btn btn-quiet btn-sm', type: 'button', onclick: async () => {
      const dir = await api.chooseFolder('לאן להעתיק את השירים?');
      if (dir) pickDrive(dir, dir.split(/[\\/]/).filter(Boolean).pop() || dir);
    } }, icon('folder-open', 'icon-sm'), 'תיקייה אחרת…');
    const refresh = h('button', { class: 'btn btn-quiet btn-sm', type: 'button', onclick: loadDrives }, icon('refresh-cw', 'icon-sm'), 'לחפש שוב');

    d.body.append(
      h('div', { class: 'tool-row tool-row-top' }, h('div', { class: 'tool-label' }, 'לאן'), h('div', { class: 'tool-stack' }, drives, h('div', { class: 'tool-actions' }, refresh, chooseFolder))),
      h('div', { class: 'tool-row' }, h('label', { class: 'tool-label', for: 'export-folder' }, 'תיקייה בנגן'), Object.assign(folderInput, { id: 'export-folder' })),
      choice('סידור', [['flat', 'הכל בתיקייה אחת'], ['singer', 'תיקייה לכל זמר'], ['topic', 'לפי נושא']], opts.layout,
        (v) => { opts.layout = v; plan(); }),
      h('label', { class: 'tool-check' }, h('input', { type: 'checkbox', checked: true, onchange: (e) => { opts.numbered = e.target.checked; plan(); } }),
        'מספור לפי סדר ההשמעה (לנגנים שמנגנים לפי שם הקובץ)'),
      h('label', { class: 'tool-check' }, convertBox,
        'להמיר ל-MP3 קבצים בפורמט אחר (M4A, FLAC, WMA…), כי רוב הנגנים מנגנים רק MP3'),
      summary);
    const progress = h('progress', { class: 'tool-progress', max: '1', value: '0', hidden: true });
    d.foot.replaceChildren(progress, h('span', { class: 'tool-foot-note' }, 'השירים במחשב לא משתנים. בעותקים בנגן נכתבים השם והזמר.'), go);

    go.addEventListener('click', async () => {
      go.disabled = true;
      const r = await api.exportRun({ ...opts, ids: songs.map((t) => t.id) }).catch((err) => ({ started: false, reason: err.message }));
      if (!r.started) {
        summary.textContent = r.reason === 'already running' ? 'העתקה אחרת עוד רצה.' : `ההעתקה לא התחילה: ${r.reason || ''}`;
        go.disabled = false;
        return;
      }
      d.el.dataset.busy = '1';
      exporting = d;
      progress.hidden = false;
      progress.max = String(info ? info.count : songs.length);
      for (const el of d.body.querySelectorAll('button, input')) el.disabled = true;
      go.replaceWith(h('button', { class: 'btn btn-outline', type: 'button', id: 'export-stop', onclick: (e) => {
        e.currentTarget.disabled = true;
        api.exportStop().catch(() => {});
        summary.textContent = 'עוצר אחרי השיר הנוכחי…';
      } }, icon('circle-stop', 'icon-sm'), 'לעצור'));
      summary.textContent = 'מעתיק…';
      d.progress = progress;
      d.summary = summary;
    });
    loadDrives();
  };

  api.on('export_progress', (p) => {
    if (!exporting) return;
    exporting.progress.value = String(p.done);
    exporting.summary.textContent = `מעתיק ${H.n(p.done)} מתוך ${H.n(p.total)}: ${p.title || ''}`;
  });
  api.on('export_done', (r) => {
    const d = exporting;
    exporting = null;
    let text;
    if (r && r.error) text = `ההעתקה נכשלה: ${r.error}`;
    else {
      const parts = [`הועתקו ${H.songs(r.copied || 0)}`];
      if (r.already) parts.push(`${H.songs(r.already)} כבר היו בנגן`);
      if (r.failed_count) parts.push(`${H.songs(r.failed_count)} לא הועתקו${r.failed[0] ? ` (${r.failed[0].reason})` : ''}`);
      if (r.cancelled) parts.push('נעצר באמצע');
      text = parts.join(' · ');
    }
    H.toast(text, { icon: 'usb', kind: r && (r.error || r.failed_count) ? 'bad' : undefined });
    if (!d) return;
    delete d.el.dataset.busy;
    d.summary.textContent = text;
    d.progress.hidden = true;
    const stop = d.el.querySelector('#export-stop');
    const done = h('div', { class: 'tool-actions' },
      r && r.folder ? h('button', { class: 'btn btn-quiet', type: 'button', onclick: () => api.openFolder(r.folder) }, icon('folder-open', 'icon-sm'), 'לפתוח את התיקייה') : null,
      h('button', { class: 'btn btn-primary', type: 'button', onclick: () => d.el.close() }, 'סיום'));
    for (const note of d.foot.querySelectorAll('.tool-foot-note')) note.textContent = '';
    if (stop) stop.replaceWith(done); else d.foot.appendChild(done);
  });

  // ------------------------------------------------------------ a ringtone
  H.openRingtone = async function openRingtone(track) {
    H.closeTrackMenu && H.closeTrackMenu();
    if (!track || !track.path) return;
    const d = dialog('ringtone', 'צלצול לטלפון', [H.trackTitle(track), track.artist].filter(Boolean).join(' · '));
    let info;
    try {
      info = await api.ringtoneInfo(track.id);
    } catch (err) {
      d.body.append(H.emptyState('לא הצלחתי להכין צלצול', err.message));
      return;
    }
    if (!info.ffmpeg) {
      d.body.append(H.emptyState('חסר רכיב ההמרה', 'בגרסה הזו אין ffmpeg, ולכן אי אפשר לחתוך שירים.'));
      return;
    }
    const duration = info.duration || track.duration || 0;
    const opts = { start: info.start || 0, length: 30, format: 'mp3' };
    const startLabel = h('span', { class: 'num tool-value' }, H.clock(opts.start));
    const slider = h('input', { type: 'range', min: '0', max: String(Math.max(1, Math.floor(duration - 5))), step: '1', value: String(Math.floor(opts.start)), 'aria-label': 'מאיפה הצלצול מתחיל' });
    H.fillRange && H.fillRange(slider);
    slider.addEventListener('input', () => {
      opts.start = Number(slider.value);
      startLabel.textContent = H.clock(opts.start);
      H.fillRange && H.fillRange(slider);
    });

    // A preview, in the dialog only: the player keeps playing what it played.
    const audio = new Audio(api.fileUrl(track.path));
    audio.preload = 'auto';
    let stopAt = 0;
    audio.addEventListener('timeupdate', () => { if (stopAt && audio.currentTime >= stopAt) { audio.pause(); setPlay(false); } });
    const listen = h('button', { class: 'btn btn-outline btn-sm', type: 'button' }, icon('play', 'icon-sm'), 'להשמיע');
    const setPlay = (on) => {
      listen.replaceChildren(icon(on ? 'pause' : 'play', 'icon-sm'), on ? 'לעצור' : 'להשמיע');
    };
    listen.addEventListener('click', () => {
      if (!audio.paused) { audio.pause(); setPlay(false); return; }
      if (H.player && H.player.toggle && H.player.mode !== 'idle') H.player.toggle(false);
      audio.currentTime = opts.start;
      stopAt = opts.start + opts.length;
      audio.play().then(() => setPlay(true)).catch(() => H.toast('לא הצלחתי להשמיע את השיר', { kind: 'bad' }));
    });
    d.el.addEventListener('close', () => { audio.pause(); audio.src = ''; });

    const result = h('p', { class: 'tool-summary', 'aria-live': 'polite' }, 'יישמר בתיקייה: ', h('bdi', { dir: 'ltr' }, info.folder));
    const make = h('button', { class: 'btn btn-primary', type: 'button' }, icon('scissors', 'icon-sm'), 'ליצור צלצול');
    make.addEventListener('click', async () => {
      make.disabled = true;
      make.replaceChildren(icon('loader-circle', 'icon-sm spin'), 'חותך…');
      const r = await api.makeRingtone(track.id, opts.start, opts.length, opts.format).catch((err) => ({ ok: false, message: err.message }));
      make.disabled = false;
      make.replaceChildren(icon('scissors', 'icon-sm'), 'ליצור צלצול');
      if (!r.ok) { result.textContent = r.message || 'לא הצלחתי'; return; }
      result.replaceChildren(`הצלצול מוכן: ${r.path.split(/[\\/]/).pop()} `,
        h('button', { class: 'btn btn-quiet btn-sm', type: 'button', onclick: () => api.showInFolder(r.path) }, icon('folder-open', 'icon-sm'), 'להציג בתיקייה'));
      H.toast('הצלצול מוכן. מעבירים אותו לטלפון בכבל או בבלוטות׳.', { icon: 'bell-ring' });
    });

    d.body.append(
      h('div', { class: 'tool-row' }, h('div', { class: 'tool-label' }, 'מאיפה'), h('div', { class: 'tool-range' }, slider, startLabel)),
      choice('אורך', (info.lengths || [20, 30, 40]).map((n) => [String(n), `${n} שניות`]), '30',
        (v) => { opts.length = Number(v); }),
      choice('לאיזה טלפון', [['mp3', 'כל טלפון (MP3)'], ['m4r', 'אייפון (M4R)']], 'mp3', (v) => { opts.format = v; }),
      h('div', { class: 'tool-actions' }, listen),
      result);
    d.foot.replaceChildren(h('span', { class: 'tool-foot-note' }, 'הצלצול נכנס ונעלם בהדרגה. השיר עצמו לא משתנה.'), make);
  };
})();
