/**
 * likes.js — Shared like toggle logic used by home, user_posts, and post pages.
 *
 * Implements optimistic UI:
 *   1. Instantly update the heart icon + count in the DOM (no wait).
 *   2. Fire the API request in the background.
 *   3. On success → confirm the server's count (source of truth).
 *   4. On failure → revert the DOM change and show a brief error message.
 */

import { getToken } from '/static/js/auth.js';

/**
 * Toggle a like on a post. Handles optimistic UI update and API call.
 *
 * @param {HTMLButtonElement} btn  - The like button element clicked.
 * @param {number|string} postId   - The ID of the post to toggle.
 */
export async function handleLikeToggle(btn, postId) {
  const token = getToken();
  if (!token) {
    // Not logged in — redirect to login
    window.location.href = '/login';
    return;
  }

  // Read current state from DOM data attributes
  const wasLiked = btn.dataset.liked === 'true';
  const prevCount = parseInt(btn.dataset.likeCount, 10) || 0;
  const newCount = wasLiked ? prevCount - 1 : prevCount + 1;

  // --- Optimistic update ---
  _applyLikeState(btn, !wasLiked, newCount);
  btn.disabled = true;

  try {
    const response = await fetch(`/api/posts/${postId}/like`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}` },
    });

    if (response.status === 401) {
      // Token expired — revert and redirect
      _applyLikeState(btn, wasLiked, prevCount);
      window.location.href = '/login';
      return;
    }

    if (!response.ok) {
      throw new Error(`Server responded with ${response.status}`);
    }

    const data = await response.json();
    // Confirm with server's authoritative count
    _applyLikeState(btn, data.liked, data.like_count);

  } catch (err) {
    console.error('Like toggle failed:', err);
    // Revert optimistic update on failure
    _applyLikeState(btn, wasLiked, prevCount);
    _showLikeError(btn);
  } finally {
    btn.disabled = false;
  }
}

/**
 * Apply like state to a button element.
 * Updates: data attributes, aria-label, heart icon class, count text.
 *
 * @param {HTMLButtonElement} btn
 * @param {boolean} liked
 * @param {number} count
 */
function _applyLikeState(btn, liked, count) {
  btn.dataset.liked = liked ? 'true' : 'false';
  btn.dataset.likeCount = count;

  const icon = btn.querySelector('.like-icon');
  const countEl = btn.querySelector('.like-count');

  if (icon) {
    icon.textContent = liked ? '❤️' : '🤍';
  }
  if (countEl) {
    countEl.textContent = count;
  }

  btn.setAttribute(
    'aria-label',
    liked ? `Unlike this post (${count} likes)` : `Like this post (${count} likes)`
  );
  btn.classList.toggle('liked', liked);
}

/**
 * Show a brief inline error message near the button.
 * Auto-removes after 3 seconds.
 *
 * @param {HTMLButtonElement} btn
 */
function _showLikeError(btn) {
  // Avoid stacking multiple error messages
  const existing = btn.parentElement.querySelector('.like-error-msg');
  if (existing) existing.remove();

  const msg = document.createElement('span');
  msg.className = 'like-error-msg text-danger ms-2';
  msg.style.fontSize = '0.8rem';
  msg.textContent = 'Could not update like. Try again.';
  btn.parentElement.appendChild(msg);

  setTimeout(() => msg.remove(), 3000);
}

/**
 * Initialise all like buttons on the current page.
 * Attaches a click handler to every [data-like-btn] element.
 *
 * Call this once after the DOM is ready (and again after
 * dynamically loading more posts via "Load More").
 *
 * @param {HTMLElement} [container=document] - Scope to search within.
 */
export function initLikeButtons(container = document) {
  container.querySelectorAll('[data-like-btn]').forEach((btn) => {
    // Avoid binding duplicate handlers if initLikeButtons is called again
    if (btn.dataset.likeInitialized) return;
    btn.dataset.likeInitialized = 'true';

    btn.addEventListener('click', () => {
      handleLikeToggle(btn, btn.dataset.postId);
    });
  });
}
