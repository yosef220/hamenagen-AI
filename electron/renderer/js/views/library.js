'use strict';

/* Library: every song on the computer, sortable and filterable, page by page. */
(function () {
  const { h, icon, api } = H;
  const root = H.$('#view-library');
  const PAGE = 200;
  const state = { sort: 'title', descending: false, filter: 'all', topic: '', text: '' };
  let loaded = [];
  let total = 0;
  let loading = false;
  let observer = null;
  let list = null;
  let sentinel = null;
  let countEl = null;

  const COLUMNS = [
    { key: null, label: '#' },
    { key: null, label: '' },
    { key: 'title', label: 'שם השיר' },
    { key: 'topic', label: 'נושא' },
    { key: 'duration', label: 'משך', end: true },
    { key: null, label: '' },
  ];

  function query(offset) {
    return {
      sort: state.sort,
      descending: state.descending,
      topic: state.filter === 'untagged' ? '__none__' : state.topic || null,
      text: state.text,
      favorites_only: state.filter === 'favorites',
      offset,
      limit: PAGE,
    };
  }

  async function loadMore(reset) {
    if (loading) return;
    if (!reset && loaded.length >= total) return;
    loading = true;
    try {
      const page = await api.listTracks(query(reset ? 0 : loaded.length));
      if (reset) {
        loaded = [];
        H.clear(list);
      }
      total = page.total;
      const start = loaded.length;
      loaded.push(...page.tracks);
      H.appendTracks(list, page.tracks, start, { source: loaded });
      countEl.textContent = total ? `${H.songs(total)}${state.text || state.filter !== 'all' || state.topic ? ' מתאימים' : ''}` : '';
      sentinel.textContent = loaded.length < total ? 'טוען עוד…' : '';
      if (!total) {
        list.appendChild(H.emptyState(
          state.filter === 'favorites' ? 'עוד לא סימנת שירים בלב' : 'לא נמצאו שירים',
          state.filter === 'favorites' ? 'לחיצה על הלב שליד שיר שומרת אותו כאן.' : 'אפשר לנסות מילה אחרת או לנקות את הסינון.'));
      }
    } catch (err) {
      H.toast(`לא הצלחתי לטעון את הספרייה: ${err.message}`, { kind: 'bad' });
    } finally {
      loading = false;
    }
  }

  function sortHeader() {
    return h('div', { class: 'tracks-head', role: 'row' }, COLUMNS.map((c) => {
      if (!c.key) return h('div', { class: c.end ? 'end' : '' }, c.label);
      const active = state.sort === c.key;
      return h('div', { class: c.end ? 'end' : '' },
        h('button', {
          class: 'sort-btn',
          type: 'button',
          'aria-sort': active ? (state.descending ? 'descending' : 'ascending') : false,
          onclick: () => {
            if (state.sort === c.key) state.descending = !state.descending;
            else { state.sort = c.key; state.descending = false; }
            render(false);
          },
        }, c.label, active ? icon(state.descending ? 'arrow-up' : 'arrow-down') : null));
    }));
  }

  async function render(refetchTopics = true) {
    const topics = refetchTopics || !H.cachedTopics ? await api.topics().catch(() => []) : H.cachedTopics;
    H.cachedTopics = topics;
    const stats = await api.overview().then((o) => o.stats).catch(() => null);

    const search = h('input', { type: 'search', placeholder: 'חיפוש בשם, זמר או אלבום', value: state.text, 'aria-label': 'חיפוש בספרייה' });
    search.addEventListener('input', H.debounce(() => { state.text = search.value; loadMore(true); }, 220));

    const seg = h('div', { class: 'segmented', role: 'group', 'aria-label': 'סינון' },
      [['all', 'הכל'], ['favorites', 'שאהבתי'], ['untagged', 'ללא נושא']].map(([key, label]) =>
        h('button', { type: 'button', 'aria-pressed': state.filter === key ? 'true' : 'false', onclick: () => { state.filter = key; render(false); } },
          key === 'favorites' ? icon('heart') : null, label)));

    const topicSelect = h('select', { class: 'select', 'aria-label': 'נושא' },
      h('option', { value: '' }, 'כל הנושאים'),
      topics.filter((t) => t.count).map((t) => h('option', { value: t.key, selected: state.topic === t.key }, `${t.label} (${H.n(t.count)})`)));
    topicSelect.disabled = state.filter === 'untagged';
    topicSelect.addEventListener('change', () => { state.topic = topicSelect.value; loadMore(true); });

    countEl = h('span', { class: 'muted num' });
    list = h('div', { class: 'tracks', role: 'list' });
    sentinel = h('div', { class: 'load-more' });

    const head = h('header', { class: 'page-head' },
      h('h1', {}, 'הספרייה'),
      stats ? h('div', { class: 'page-meta num' }, `${H.songs(stats.tracks)} · ${H.span(stats.seconds)} של מוזיקה`) : null,
      h('div', { class: 'page-actions' },
        h('button', { class: 'btn btn-outline', type: 'button', onclick: () => playAll(false) }, icon('play'), 'נגן הכל'),
        h('button', { class: 'btn btn-outline', type: 'button', onclick: () => playAll(true) }, icon('shuffle'), 'ערבב הכל')));

    H.clear(root).append(
      head,
      h('div', { class: 'toolbar' }, h('label', { class: 'field' }, icon('search'), search), seg, topicSelect, countEl),
      h('div', {}, sortHeader(), list, sentinel),
    );

    if (observer) observer.disconnect();
    observer = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) loadMore(false);
    }, { root: H.$('#main'), rootMargin: '400px' });
    observer.observe(sentinel);
    await loadMore(true);
  }

  async function playAll(shuffle) {
    // The queue is the whole filtered library, not only the loaded pages.
    const all = [];
    let offset = 0;
    try {
      while (offset < Math.max(total, 1) && offset < 5000) {
        const page = await api.listTracks({ ...query(offset), limit: 1000 });
        all.push(...page.tracks);
        if (page.tracks.length < 1000) break;
        offset += 1000;
      }
    } catch (err) {
      H.toast(err.message, { kind: 'bad' });
    }
    if (all.length) H.player.playList(all, 0, { shuffle });
  }

  api.on('favorites-changed', () => {
    if (!root.hidden && state.filter === 'favorites') loadMore(true);
  });

  H.views = H.views || {};
  H.views.library = { show: () => render(true), refresh: () => render(true) };
})();
