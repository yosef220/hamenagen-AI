'use strict';

/*
 * Home: the luach (today in Hebrew letters and what it calls for), the
 * request line, the topics, and what was played and added lately.
 */
(function () {
  const { h, icon, api } = H;
  const root = H.$('#view-home');
  let firstPaint = true;
  let today = null;

  const SUGGESTIONS = [
    'שעה של שירי שבת',
    'השירים האחרונים שהורדתי',
    'השירים שאהבתי',
    'חצי שעה של מוזיקה ווקאלית',
    'מה ששמעתי לאחרונה',
    'תשמיע משהו אקראי',
  ];

  // ------------------------------------------------------------ the luach
  function luach(t) {
    const heb = t.hebrew;
    const date = h('div', { class: 'luach-date' },
      h('div', { class: 'luach-day', 'aria-hidden': 'true' }, heb.day_text),
      h('div', { class: 'luach-rest' },
        h('div', { class: 'luach-month' }, `ב${heb.month_name} ${heb.year_text}`),
        h('div', { class: 'luach-civil' }, `${t.weekday} · ${H.civilDate(t.gregorian)}`)));

    const occasionBox = h('div', { class: 'luach-occasion' });
    const primary = t.primary;
    const others = t.occasions.filter((o) => !primary || o.key !== primary.key);

    if (primary) {
      occasionBox.append(
        h('div', { class: 'luach-kicker' }, 'היום'),
        h('div', { class: 'luach-title' }, primary.label),
        primary.detail ? h('div', { class: 'luach-detail' }, primary.detail) : null,
        h('div', { class: 'luach-actions' },
          primary.count
            ? h('button', { class: 'btn btn-gold', type: 'button', onclick: () => H.playTopic(primary.topic) },
              icon('play'), `${primary.phrase} · ${H.n(primary.count)}`)
            : h('span', { class: 'luach-note' }, `אין עדיין ${primary.phrase} במאגר — אפשר לבקש ולהוריד מהרשת.`),
          others.filter((o) => o.topic && o.count).map((o) =>
            h('button', { class: 'chip', type: 'button', onclick: () => H.playTopic(o.topic) }, `גם: ${o.phrase}`))),
        others.filter((o) => !o.topic).map((o) => h('div', { class: 'luach-note' }, [o.label, o.detail].filter(Boolean).join(' · '))),
      );
    } else if (t.occasions.length) {
      // A day with an occasion that suggests no music (Tisha B'Av, or the
      // Omer count with vocal suggestions turned off).
      const o = t.occasions[0];
      occasionBox.append(
        h('div', { class: 'luach-kicker' }, 'היום'),
        h('div', { class: 'luach-title' }, o.label),
        o.detail ? h('div', { class: 'luach-detail' }, o.detail) : null,
      );
    } else if (t.next) {
      const n = t.next;
      occasionBox.append(
        h('div', { class: 'luach-kicker' }, `${H.days(n.days)} · ${n.hebrew}`),
        h('div', { class: 'luach-title' }, n.label),
        h('div', { class: 'luach-detail' }, `${n.weekday}, ${H.civilDate(n.gregorian)}`),
        h('div', { class: 'luach-actions' },
          n.count
            ? h('button', { class: 'btn btn-gold', type: 'button', onclick: () => H.playTopic(n.topic) }, icon('play'), `להתכונן: ${n.phrase}`)
            : h('span', { class: 'luach-note' }, `עוד אין ${n.phrase} במאגר. אפשר לבקש אותם כבר עכשיו.`)),
      );
    } else {
      occasionBox.append(h('div', { class: 'luach-title' }, 'יום רגיל'), h('div', { class: 'luach-detail' }, 'מה בא לשמוע?'));
    }

    const panel = h('section', { class: `luach${firstPaint ? ' enter' : ''}`, 'aria-label': `היום ${heb.text}` }, date, occasionBox);
    firstPaint = false;
    return panel;
  }

  // ------------------------------------------------------------ request line
  function askLine() {
    const input = h('input', {
      class: 'ask-input',
      id: 'ask-input',
      type: 'text',
      autocomplete: 'off',
      spellcheck: 'false',
      placeholder: 'מה לשמוע? למשל: שעה של שירי שבת',
      'aria-label': 'בקשה בשפה חופשית',
    });
    const form = h('form', { class: 'ask-form', role: 'search', onsubmit: (e) => { e.preventDefault(); H.ask(input.value); } },
      icon('search'), input,
      h('button', { class: 'btn btn-primary', type: 'submit' }, 'השמע'));
    const chips = SUGGESTIONS.slice();
    if (today && today.primary && today.primary.count) chips.unshift(`שעה של ${today.primary.phrase}`);
    return h('section', { class: 'ask', 'aria-label': 'בקשה' }, form,
      h('div', { class: 'chips' }, [...new Set(chips)].slice(0, 6).map((text) =>
        h('button', { class: 'chip', type: 'button', onclick: () => H.ask(text) }, text))));
  }

  // ------------------------------------------------------------ sections
  function topicsSection(topics) {
    const withSongs = topics.filter((t) => t.count);
    const shown = (withSongs.length >= 4 ? withSongs : topics).slice(0, 8);
    return h('section', { class: 'section', 'aria-label': 'נושאים' },
      h('div', { class: 'section-head' },
        h('h2', {}, 'נושאים'),
        h('button', { class: 'btn btn-quiet more', type: 'button', onclick: () => H.go('topics') }, 'כל הנושאים', icon('chevron-left', 'icon-sm'))),
      h('div', { class: 'tiles' }, shown.map((t) => H.topicTile(t))));
  }

  function listSection(title, tracks, emptyText, more) {
    return h('section', { class: 'section', 'aria-label': title },
      h('div', { class: 'section-head' }, h('h2', {}, title), more || null),
      tracks.length ? H.trackList(tracks.slice(0, 6), { compact: true }) : h('p', { class: 'muted' }, emptyText));
  }

  function scanningPanel(overview) {
    return h('section', { class: 'section', 'aria-label': 'סריקה' },
      H.emptyState(
        overview.scanning ? 'המנגן מחפש שירים במחשב' : 'עוד לא נמצאו שירים',
        overview.scanning
          ? 'הסריקה רצה ברקע ולא מפריעה לשום דבר. השירים יופיעו כאן מיד כשתסתיים.'
          : 'המנגן סורק את תיקיית המשתמש ואת שאר הכוננים. אפשר גם לבחור תיקיות מסוימות.',
        h('button', { class: 'btn btn-outline', type: 'button', onclick: () => H.go('settings', { focus: 'library' }) }, icon('folder-plus'), 'בחירת תיקיות'),
        overview.scanning ? null : h('button', { class: 'btn btn-quiet', type: 'button', onclick: () => H.rescan() }, icon('refresh-cw'), 'לסרוק שוב')));
  }

  // ------------------------------------------------------------ render
  async function render() {
    let overview;
    try {
      [today, overview] = await Promise.all([api.today(), api.overview()]);
    } catch (err) {
      H.clear(root).appendChild(H.emptyState('לא הצלחתי לטעון את דף הבית', err.message));
      return;
    }
    H.topicLabels = Object.fromEntries(overview.topics.map((t) => [t.key, t.label]));
    H.updateRail(overview);
    const ask = askLine();
    const parts = [luach(today), ask];
    if (!overview.stats.tracks) {
      parts.push(scanningPanel(overview));
    } else {
      parts.push(topicsSection(overview.topics));
      parts.push(h('div', { class: 'home-cols' },
        listSection('שמעת לאחרונה', overview.history, 'השירים שתשמעו יופיעו כאן.',
          overview.history.length ? h('button', { class: 'btn btn-quiet more', type: 'button', onclick: () => H.go('results', { kind: 'history' }) }, 'הכל', icon('chevron-left', 'icon-sm')) : null),
        listSection('נוספו לאחרונה', overview.recent, 'עוד לא נוספו שירים.',
          h('button', { class: 'btn btn-quiet more', type: 'button', onclick: () => H.go('results', { kind: 'recent_downloaded' }) }, 'הכל', icon('chevron-left', 'icon-sm')))));
    }
    H.clear(root).append(...parts);
    H.markActive(root);
  }

  H.views = H.views || {};
  H.views.home = {
    show: render,
    refresh: render,
    focusAsk() {
      const input = H.$('#ask-input');
      if (input) input.focus();
    },
  };
})();
