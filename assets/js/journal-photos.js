(() => {
  const data = document.querySelector('[data-journal-photo-data]');
  const grid = document.getElementById('journal-photo-grid');
  if (!data || !grid) return;

  let pool;
  try { pool = JSON.parse(data.textContent); } catch { return; }
  if (!Array.isArray(pool) || !pool.length) return;

  const shuffle = (items) => {
    const result = [...items];
    for (let index = result.length - 1; index > 0; index--) {
      const other = Math.floor(Math.random() * (index + 1));
      [result[index], result[other]] = [result[other], result[index]];
    }
    return result;
  };
  const byPost = new Map();
  for (const photo of pool) {
    if (!byPost.has(photo.post_url)) byPost.set(photo.post_url, []);
    byPost.get(photo.post_url).push(photo);
  }

  const selected = shuffle([...byPost.values()]).slice(0, 3).map((photos) => photos[Math.floor(Math.random() * photos.length)]);
  const fragment = document.createDocumentFragment();
  for (const photo of selected) {
    const link = document.createElement('a');
    link.href = photo.post_url;
    const figure = document.createElement('figure');
    const image = document.createElement('img');
    Object.assign(image, { src: photo.src, alt: photo.alt, width: photo.width, height: photo.height, loading: 'lazy', decoding: 'async' });
    const caption = document.createElement('figcaption');
    caption.textContent = photo.post_title;
    figure.append(image, caption);
    link.append(figure);
    fragment.append(link);
  }
  grid.replaceChildren(fragment);
})();
