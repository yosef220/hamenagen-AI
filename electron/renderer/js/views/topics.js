'use strict';

/* Topics: every occasion and mood the classifier knows, as letter tiles. */
(function () {
  const { h, api } = H;
  const root = H.$('#view-topics');

  async function render() {
    let topics;
    try {
      topics = await api.topics();
    } catch (err) {
      H.clear(root).appendChild(H.emptyState('לא הצלחתי לטעון את הנושאים', err.message));
      return;
    }
    H.cachedTopics = topics;
    H.topicLabels = Object.fromEntries(topics.map((t) => [t.key, t.label]));
    const classified = topics.reduce((s, t) => s + (t.count || 0), 0);
    H.clear(root).append(
      h('header', { class: 'page-head' },
        h('h1', {}, 'נושאים'),
        h('div', { class: 'page-meta' }, classified
          ? 'כל שיר משויך לפי שמו, המילון והמודל המקומי. שיר יכול להופיע ביותר מנושא אחד.'
          : 'הנושאים יתמלאו אחרי שהסריקה תמצא שירים.')),
      h('div', { class: 'tiles tiles-lg' }, topics.map((t) => H.topicTile(t, { phrase: true }))),
    );
  }

  H.views = H.views || {};
  H.views.topics = { show: render, refresh: render };
})();
