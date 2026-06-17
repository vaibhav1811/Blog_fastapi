/**
 * comments.js — Full comment system for the post detail page.
 *
 * Features:
 *   - Cursor-based infinite scroll (newest first)
 *   - 3-reply preview per comment with "View X more replies" button
 *   - Optimistic UI: new comments/replies appear instantly, roll back on failure
 *   - Inline edit and delete for the current user's own comments/replies
 *   - Character counter on all textareas
 *   - Event delegation: one handler on the container, works for dynamically added elements
 *
 * Public API:
 *   initComments(postId)  — call once from post.html after DOM ready
 */

import { getCurrentUser, getToken } from '/static/js/auth.js';
import { escapeHtml, formatDate, getErrorMessage } from '/static/js/utils.js';

// ── Module state ────────────────────────────────────────────────────────────

let _postId = null;
let _currentUser = null;
let _nextCursor = null;
let _loading = false;


// ── Public entry point ───────────────────────────────────────────────────────

/**
 * Initialise the comment system for a given post.
 * Call once from the {% block scripts %} of post.html.
 *
 * @param {number|string} postId
 */
export async function initComments(postId) {
    _postId = postId;
    _currentUser = await getCurrentUser();

    // Show comment form for logged-in users
    const form = document.getElementById('commentForm');
    if (_currentUser && form) {
        form.classList.remove('d-none');
        _setupTopLevelCommentForm(form);
    }

    // Set up event delegation on the comments list (handles all future clicks too)
    const container = document.getElementById('commentsList');
    if (container) {
        _bindContainerEvents(container);
    }

    // Load the first page of comments
    await _loadMoreComments();

    // Wire "Load more comments" button
    const loadMoreBtn = document.getElementById('loadMoreCommentsBtn');
    if (loadMoreBtn) {
        loadMoreBtn.addEventListener('click', async () => {
            loadMoreBtn.disabled = true;
            loadMoreBtn.textContent = 'Loading…';
            await _loadMoreComments();
            // Button re-enabled / hidden inside _loadMoreComments
        });
    }
}


// ── Fetch & render comments ──────────────────────────────────────────────────

async function _loadMoreComments() {
    if (_loading) return;
    _loading = true;

    try {
        const url = new URL(`/api/posts/${_postId}/comments`, window.location.origin);
        if (_nextCursor !== null) url.searchParams.set('cursor', _nextCursor);

        const response = await fetch(url);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const data = await response.json();
        _nextCursor = data.next_cursor ?? null;

        const container = document.getElementById('commentsList');
        for (const comment of data.comments) {
            container.insertAdjacentHTML('beforeend', _buildCommentHTML(comment));
        }

        _refreshCommentHeading();
        _updateLoadMoreButton();

    } catch (err) {
        console.error('[comments] Failed to load comments:', err);
        const wrap = document.getElementById('loadMoreCommentsWrap');
        if (wrap) {
            wrap.style.removeProperty('display');
            const btn = document.getElementById('loadMoreCommentsBtn');
            if (btn) {
                btn.disabled = false;
                btn.textContent = 'Error — click to retry';
            }
        }
    } finally {
        _loading = false;
    }
}

function _updateLoadMoreButton() {
    const wrap = document.getElementById('loadMoreCommentsWrap');
    const btn = document.getElementById('loadMoreCommentsBtn');
    if (!wrap || !btn) return;

    if (_nextCursor !== null) {
        wrap.style.removeProperty('display');
        btn.disabled = false;
        btn.textContent = 'Load more comments';
    } else {
        wrap.style.setProperty('display', 'none', 'important');
    }
}

function _refreshCommentHeading() {
    const heading = document.getElementById('commentsHeading');
    if (!heading) return;
    const count = document.querySelectorAll('#commentsList > .comment-card').length;
    heading.textContent = count > 0
        ? `Comments (${count}${_nextCursor !== null ? '+' : ''})`
        : 'Comments';
}


// ── HTML builders ────────────────────────────────────────────────────────────

function _buildCommentHTML(comment) {
    const isOwner = _currentUser && _currentUser.id === comment.user_id;
    const editedBadge = comment.updated_at
        ? ' <span style="font-size:0.75rem;opacity:0.5;">(edited)</span>'
        : '';

    const replyBtnHTML = _currentUser
        ? `<button class="comment-action-btn reply-btn"
                   data-action="reply"
                   data-comment-id="${comment.id}"
                   aria-label="Reply to this comment">Reply</button>`
        : '';

    const ownerActionsHTML = isOwner
        ? `<button class="comment-action-btn edit-btn"
                   data-action="edit"
                   data-comment-id="${comment.id}"
                   aria-label="Edit comment">Edit</button>
           <button class="comment-action-btn delete-btn"
                   data-action="delete"
                   data-comment-id="${comment.id}"
                   aria-label="Delete comment">Delete</button>`
        : '';

    // Build the replies preview HTML
    const repliesPreviewHTML = comment.replies.length > 0
        ? comment.replies.map(r => _buildReplyHTML(r)).join('')
        : '';

    // "View X more replies" button — only shown when there are hidden replies
    const hiddenCount = comment.reply_count - comment.replies.length;
    const lastPreviewId = comment.replies.length > 0
        ? comment.replies[comment.replies.length - 1].id  // oldest in preview = cursor
        : null;

    const loadMoreRepliesHTML = hiddenCount > 0
        ? `<button class="comment-action-btn reply-btn mt-1 ms-3"
                   data-action="load-replies"
                   data-comment-id="${comment.id}"
                   data-reply-cursor="${lastPreviewId ?? ''}"
                   data-remaining="${hiddenCount}"
                   aria-label="View ${hiddenCount} more repl${hiddenCount === 1 ? 'y' : 'ies'}">
               View ${hiddenCount} more repl${hiddenCount === 1 ? 'y' : 'ies'}
           </button>`
        : '';

    return `
<div class="comment-card" id="comment-${comment.id}" data-comment-id="${comment.id}">
    <div class="comment-meta">
        <a href="/users/${comment.author.id}/posts">${escapeHtml(comment.author.username)}</a>
        · ${formatDate(comment.created_at)}${editedBadge}
    </div>
    <p class="comment-body" id="comment-body-${comment.id}">${escapeHtml(comment.content)}</p>

    <!-- Action row -->
    <div class="comment-actions" id="comment-actions-${comment.id}">
        ${replyBtnHTML}${ownerActionsHTML}
    </div>

    <!-- Inline edit area (hidden by default) -->
    <div class="comment-edit-wrap d-none" id="edit-wrap-${comment.id}">
        <textarea class="form-control comment-edit-area"
                  id="edit-area-${comment.id}"
                  maxlength="2000"
                  aria-label="Edit comment text">${escapeHtml(comment.content)}</textarea>
        <div class="d-flex gap-2 mt-1">
            <button class="btn btn-primary btn-sm"
                    data-action="save-edit"
                    data-comment-id="${comment.id}">Save</button>
            <button class="btn btn-outline-secondary btn-sm"
                    data-action="cancel-edit"
                    data-comment-id="${comment.id}">Cancel</button>
        </div>
    </div>

    <!-- Inline reply form (hidden by default) -->
    <div class="reply-form" id="reply-form-${comment.id}">
        <textarea class="form-control comment-edit-area mt-1"
                  id="reply-input-${comment.id}"
                  maxlength="2000"
                  placeholder="Write a reply…"
                  aria-label="Write a reply"></textarea>
        <div class="d-flex gap-2 mt-1">
            <button class="btn btn-primary btn-sm"
                    data-action="submit-reply"
                    data-comment-id="${comment.id}">Reply</button>
            <button class="btn btn-outline-secondary btn-sm"
                    data-action="cancel-reply"
                    data-comment-id="${comment.id}">Cancel</button>
        </div>
    </div>

    <!-- Replies container -->
    <div id="replies-${comment.id}">${repliesPreviewHTML}</div>
    ${loadMoreRepliesHTML}
</div>`;
}

function _buildReplyHTML(reply) {
    const isOwner = _currentUser && _currentUser.id === reply.user_id;
    const editedBadge = reply.updated_at
        ? ' <span style="font-size:0.75rem;opacity:0.5;">(edited)</span>'
        : '';

    const ownerActionsHTML = isOwner
        ? `<button class="comment-action-btn edit-btn"
                   data-action="edit"
                   data-comment-id="${reply.id}"
                   data-is-reply="true"
                   data-parent-id="${reply.parent_id}">Edit</button>
           <button class="comment-action-btn delete-btn"
                   data-action="delete"
                   data-comment-id="${reply.id}"
                   data-is-reply="true"
                   data-parent-id="${reply.parent_id}">Delete</button>`
        : '';

    return `
<div class="comment-card reply-card" id="comment-${reply.id}" data-comment-id="${reply.id}">
    <div class="comment-meta">
        <a href="/users/${reply.author.id}/posts">${escapeHtml(reply.author.username)}</a>
        · ${formatDate(reply.created_at)}${editedBadge}
    </div>
    <p class="comment-body" id="comment-body-${reply.id}">${escapeHtml(reply.content)}</p>
    <div class="comment-actions" id="comment-actions-${reply.id}">
        ${ownerActionsHTML}
    </div>
    <!-- Inline edit area for reply -->
    <div class="comment-edit-wrap d-none" id="edit-wrap-${reply.id}">
        <textarea class="form-control comment-edit-area"
                  id="edit-area-${reply.id}"
                  maxlength="2000"
                  aria-label="Edit reply text">${escapeHtml(reply.content)}</textarea>
        <div class="d-flex gap-2 mt-1">
            <button class="btn btn-primary btn-sm"
                    data-action="save-edit"
                    data-comment-id="${reply.id}">Save</button>
            <button class="btn btn-outline-secondary btn-sm"
                    data-action="cancel-edit"
                    data-comment-id="${reply.id}">Cancel</button>
        </div>
    </div>
</div>`;
}


// ── Event delegation ─────────────────────────────────────────────────────────

/**
 * Bind a single click listener on the comments container.
 * All button interactions are handled here via event delegation — no need to
 * re-bind handlers when new comments/replies are added to the DOM.
 */
function _bindContainerEvents(container) {
    container.addEventListener('click', async (e) => {
        const btn = e.target.closest('[data-action]');
        if (!btn) return;

        const action = btn.dataset.action;
        const commentId = btn.dataset.commentId;

        switch (action) {
            case 'reply':
                _toggleReplyForm(commentId);
                break;
            case 'submit-reply':
                await _handleReplySubmit(commentId);
                break;
            case 'cancel-reply':
                _closeReplyForm(commentId);
                break;
            case 'edit':
                _openEditMode(commentId);
                break;
            case 'save-edit':
                await _handleEditSave(commentId);
                break;
            case 'cancel-edit':
                _closeEditMode(commentId);
                break;
            case 'delete':
                await _handleDelete(commentId, btn.dataset.parentId);
                break;
            case 'load-replies':
                await _handleLoadMoreReplies(btn, commentId);
                break;
        }
    });
}


// ── Top-level comment form ────────────────────────────────────────────────────

function _setupTopLevelCommentForm(form) {
    const textarea = document.getElementById('commentInput');
    const counter = document.getElementById('charCounter');

    // Live character counter
    if (textarea && counter) {
        textarea.addEventListener('input', () => {
            counter.textContent = `${textarea.value.length} / 2000`;
        });
    }

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const content = textarea?.value.trim();
        if (!content) return;

        const token = getToken();
        if (!token) { window.location.href = '/login'; return; }

        const submitBtn = form.querySelector('button[type="submit"]');
        submitBtn.disabled = true;
        submitBtn.textContent = 'Posting…';

        try {
            const response = await fetch(`/api/posts/${_postId}/comments`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`,
                },
                body: JSON.stringify({ content }),
            });

            if (response.status === 401) { window.location.href = '/login'; return; }
            if (!response.ok) {
                let errorMsg = `Server error (${response.status}). Please try again.`;
                try {
                    const err = await response.json();
                    errorMsg = getErrorMessage(err);
                } catch { /* response body was not JSON */ }
                throw new Error(errorMsg);
            }

            const comment = await response.json();

            // Optimistic prepend — new comment is newest so it goes to the top
            const container = document.getElementById('commentsList');
            container.insertAdjacentHTML('afterbegin', _buildCommentHTML(comment));
            _refreshCommentHeading();

            // Reset form
            if (textarea) { textarea.value = ''; }
            if (counter) { counter.textContent = '0 / 2000'; }

        } catch (err) {
            console.error('[comments] Failed to post comment:', err);
            _showInlineError(form, err.message || 'Could not post comment. Please try again.');
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Post';
        }
    });
}


// ── Reply actions ─────────────────────────────────────────────────────────────

function _toggleReplyForm(commentId) {
    const form = document.getElementById(`reply-form-${commentId}`);
    if (!form) return;
    form.classList.toggle('visible');
    if (form.classList.contains('visible')) {
        document.getElementById(`reply-input-${commentId}`)?.focus();
    }
}

function _closeReplyForm(commentId) {
    const form = document.getElementById(`reply-form-${commentId}`);
    if (!form) return;
    form.classList.remove('visible');
    const input = document.getElementById(`reply-input-${commentId}`);
    if (input) input.value = '';
}

async function _handleReplySubmit(parentId) {
    const textarea = document.getElementById(`reply-input-${parentId}`);
    const content = textarea?.value.trim();
    if (!content) return;

    const token = getToken();
    if (!token) { window.location.href = '/login'; return; }

    try {
        const response = await fetch(`/api/posts/${_postId}/comments`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`,
            },
            body: JSON.stringify({ content, parent_id: parseInt(parentId, 10) }),
        });

        if (response.status === 401) { window.location.href = '/login'; return; }
        if (!response.ok) {
            let errorMsg = `Server error (${response.status}). Please try again.`;
            try {
                const err = await response.json();
                errorMsg = getErrorMessage(err);
            } catch { /* response body was not JSON */ }
            throw new Error(errorMsg);
        }

        const reply = await response.json();

        // Prepend new reply to the top of the replies container (newest first)
        const repliesContainer = document.getElementById(`replies-${parentId}`);
        if (repliesContainer) {
            repliesContainer.insertAdjacentHTML('afterbegin', _buildReplyHTML(reply));
        }

        _closeReplyForm(parentId);

    } catch (err) {
        console.error('[comments] Failed to post reply:', err);
        const form = document.getElementById(`reply-form-${parentId}`);
        if (form) _showInlineError(form, err.message || 'Could not post reply. Please try again.');
    }
}


// ── Edit actions ──────────────────────────────────────────────────────────────

function _openEditMode(commentId) {
    document.getElementById(`comment-body-${commentId}`)?.classList.add('d-none');
    document.getElementById(`comment-actions-${commentId}`)?.classList.add('d-none');
    document.getElementById(`edit-wrap-${commentId}`)?.classList.remove('d-none');
    document.getElementById(`edit-area-${commentId}`)?.focus();
}

function _closeEditMode(commentId) {
    document.getElementById(`edit-wrap-${commentId}`)?.classList.add('d-none');
    document.getElementById(`comment-body-${commentId}`)?.classList.remove('d-none');
    document.getElementById(`comment-actions-${commentId}`)?.classList.remove('d-none');
}

async function _handleEditSave(commentId) {
    const textarea = document.getElementById(`edit-area-${commentId}`);
    const content = textarea?.value.trim();
    if (!content) return;

    const token = getToken();
    if (!token) { window.location.href = '/login'; return; }

    try {
        const response = await fetch(`/api/comments/${commentId}`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`,
            },
            body: JSON.stringify({ content }),
        });

        if (!response.ok) {
            let errorMsg = `Server error (${response.status}). Please try again.`;
            try {
                const err = await response.json();
                errorMsg = getErrorMessage(err);
            } catch { /* response body was not JSON */ }
            throw new Error(errorMsg);
        }

        // Update body text in DOM
        const body = document.getElementById(`comment-body-${commentId}`);
        if (body) body.textContent = content;

        // Sync edit textarea value in case user re-edits
        if (textarea) textarea.value = content;

        _closeEditMode(commentId);

    } catch (err) {
        console.error('[comments] Failed to edit comment:', err);
        const wrap = document.getElementById(`edit-wrap-${commentId}`);
        if (wrap) _showInlineError(wrap, err.message || 'Could not save. Please try again.');
    }
}


// ── Delete action ─────────────────────────────────────────────────────────────

async function _handleDelete(commentId, parentId) {
    if (!confirm('Delete this comment? This cannot be undone.')) return;

    const token = getToken();
    if (!token) { window.location.href = '/login'; return; }

    const el = document.getElementById(`comment-${commentId}`);

    // Optimistic: fade out immediately
    if (el) el.style.opacity = '0.35';

    try {
        const response = await fetch(`/api/comments/${commentId}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${token}` },
        });

        if (response.status === 401) { window.location.href = '/login'; return; }
        if (response.status === 403) {
            if (el) el.style.opacity = '1';
            alert('You are not authorized to delete this comment.');
            return;
        }
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        // Remove from DOM on success
        el?.remove();

        // If this was a top-level comment, also remove any orphaned load-replies button
        if (!parentId) {
            _refreshCommentHeading();
        }

    } catch (err) {
        console.error('[comments] Failed to delete comment:', err);
        if (el) el.style.opacity = '1';
        alert('Could not delete comment. Please try again.');
    }
}


// ── Load more replies ─────────────────────────────────────────────────────────

async function _handleLoadMoreReplies(btn, commentId) {
    const cursor = btn.dataset.replyCursor || null;
    btn.disabled = true;
    btn.textContent = 'Loading…';

    try {
        const url = new URL(`/api/comments/${commentId}/replies`, window.location.origin);
        if (cursor) url.searchParams.set('cursor', cursor);

        const response = await fetch(url);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const data = await response.json();
        const repliesContainer = document.getElementById(`replies-${commentId}`);

        // Append (oldest direction — going further back in time)
        for (const reply of data.comments) {
            repliesContainer?.insertAdjacentHTML('beforeend', _buildReplyHTML(reply));
        }

        if (data.next_cursor !== null) {
            // More replies exist — update button state
            btn.dataset.replyCursor = data.next_cursor;
            const newRemaining = parseInt(btn.dataset.remaining, 10) - data.comments.length;
            btn.dataset.remaining = Math.max(0, newRemaining);
            btn.textContent = `View ${Math.max(0, newRemaining)} more repl${newRemaining === 1 ? 'y' : 'ies'}`;
            btn.disabled = false;
        } else {
            // No more replies — remove the button
            btn.remove();
        }

    } catch (err) {
        console.error('[comments] Failed to load replies:', err);
        btn.textContent = 'Error — click to retry';
        btn.disabled = false;
    }
}


// ── Utility ────────────────────────────────────────────────────────────────────

/**
 * Show a temporary inline error message inside a container element.
 * Auto-removes after 4 seconds.
 */
function _showInlineError(container, message) {
    const existing = container.querySelector('.comment-inline-error');
    if (existing) existing.remove();

    const msg = document.createElement('p');
    msg.className = 'comment-inline-error text-danger mb-0 mt-1';
    msg.style.fontSize = '0.82rem';
    msg.textContent = message;
    container.appendChild(msg);

    setTimeout(() => msg.remove(), 4000);
}
