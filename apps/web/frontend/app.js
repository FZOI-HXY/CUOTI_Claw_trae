/**
 * 错题管理系统 - Claw
 * 前端应用逻辑 - 支持文件夹批量上传
 */
(function () {
    'use strict';

    // ============ 配置 ============
    const API_BASE = window.location.origin;
    const STEPS = ['upload', 'analyze', 'report'];

    // ============ 状态管理 ============
    const state = {
        currentView: 'upload',
        fileQueue: [],          // [{ file, name, size, status: 'pending'|'uploading'|'processing'|'done'|'error', fileId, error, result }]
        processing: false,
        batchResults: [],       // 批量处理结果汇总
        serverConnected: false,
    };

    // ============ DOM引用 ============
    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    const dom = {
        uploadZone: $('#upload-zone'),
        fileInput: $('#file-input'),
        folderInput: $('#folder-input'),
        fileQueueSection: $('#file-queue-section'),
        fileQueueList: $('#file-queue-list'),
        queueCount: $('#queue-count'),
        previewSection: $('#preview-section'),
        previewOriginal: $('#preview-original'),
        progressSection: $('#progress-section'),
        batchProgressText: $('#batch-progress-text'),
        progressBar: $('#progress-bar'),
        progressText: $('#progress-text'),
        progressSteps: $('#progress-steps'),
        resultSection: $('#result-section'),
        resultStats: $('#result-stats'),
        batchResults: $('#batch-results'),
        markdownPreview: $('#markdown-preview'),
        mdContent: $('#md-content'),
        historyTbody: $('#history-tbody'),
        reportsGrid: $('#reports-grid'),
        statusDot: $('#status-dot'),
        statusText: $('#status-text'),
        toastContainer: $('#toast-container'),
    };

    // ============ 工具函数 ============
    function formatFileSize(bytes) {
        if (bytes < 1024) return bytes + ' B';
        const formatter = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 1 });
        if (bytes < 1024 * 1024) return formatter.format(bytes / 1024) + ' KB';
        return formatter.format(bytes / (1024 * 1024)) + ' MB';
    }

    function formatTime(iso) {
        const d = new Date(iso);
        return d.toLocaleString('zh-CN', {
            month: '2-digit', day: '2-digit',
            hour: '2-digit', minute: '2-digit', second: '2-digit'
        });
    }

    function toast(message, type = 'info') {
        const icons = { success: '\u2713', error: '\u2717', warning: '\u26A0', info: '\u2139' };
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.innerHTML = `
            <span class="toast-icon">${icons[type] || icons.info}</span>
            <span class="toast-message"></span>
        `;
        // 使用 textContent 防止 XSS
        toast.querySelector('.toast-message').textContent = message;
        dom.toastContainer.appendChild(toast);
        setTimeout(() => toast.remove(), 3200);
    }

    // ============ 粒子背景 ============
    function initParticles() {
        // 检测 prefers-reduced-motion
        const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
        if (prefersReducedMotion.matches) return; // 用户偏好减少动画，不启动粒子

        const canvas = $('#particles-canvas');
        const ctx = canvas.getContext('2d');
        let particles = [];
        let animId;
        let running = false;

        function resize() {
            canvas.width = window.innerWidth;
            canvas.height = window.innerHeight;
        }

        function createParticles() {
            const count = Math.floor((canvas.width * canvas.height) / 15000);
            particles = [];
            for (let i = 0; i < count; i++) {
                particles.push({
                    x: Math.random() * canvas.width,
                    y: Math.random() * canvas.height,
                    vx: (Math.random() - 0.5) * 0.3,
                    vy: (Math.random() - 0.5) * 0.3,
                    size: Math.random() * 1.5 + 0.5,
                    opacity: Math.random() * 0.5 + 0.1,
                });
            }
        }

        function animate() {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            particles.forEach((p) => {
                p.x += p.vx;
                p.y += p.vy;
                if (p.x < 0) p.x = canvas.width;
                if (p.x > canvas.width) p.x = 0;
                if (p.y < 0) p.y = canvas.height;
                if (p.y > canvas.height) p.y = 0;
                ctx.beginPath();
                ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
                ctx.fillStyle = `rgba(245, 158, 11, ${p.opacity})`;
                ctx.fill();
            });

            for (let i = 0; i < particles.length; i++) {
                for (let j = i + 1; j < particles.length; j++) {
                    const dx = particles[i].x - particles[j].x;
                    const dy = particles[i].y - particles[j].y;
                    const dist = Math.sqrt(dx * dx + dy * dy);
                    if (dist < 120) {
                        ctx.beginPath();
                        ctx.moveTo(particles[i].x, particles[i].y);
                        ctx.lineTo(particles[j].x, particles[j].y);
                        ctx.strokeStyle = `rgba(245, 158, 11, ${0.06 * (1 - dist / 120)})`;
                        ctx.stroke();
                    }
                }
            }
            if (running) animId = requestAnimationFrame(animate);
        }

        function startAnim() {
            if (running) return;
            running = true;
            animate();
        }

        function stopAnim() {
            running = false;
            if (animId) cancelAnimationFrame(animId);
        }

        resize();
        createParticles();
        startAnim();
        // debounce resize 事件
        let resizeTimer;
        window.addEventListener('resize', () => {
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(() => { resize(); createParticles(); }, 200);
        });
        // 页面不可见时暂停粒子动画以节省资源
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                stopAnim();
            } else {
                startAnim();
            }
        });
    }

    // ============ 视图切换 ============
    let viewLoadController = null;

    function switchView(viewName) {
        state.currentView = viewName;
        $$('.view-panel').forEach(p => p.classList.remove('active'));
        $$('.nav-btn').forEach(b => {
            b.classList.remove('active');
            b.removeAttribute('aria-current');
        });

        const panel = $(`#view-${viewName}`);
        const btn = document.querySelector(`[data-view="${viewName}"]`);

        if (panel) panel.classList.add('active');
        if (btn) {
            btn.classList.add('active');
            btn.setAttribute('aria-current', 'page');
        }

        // 取消前一次视图加载请求，避免竞态
        if (viewLoadController) {
            viewLoadController.abort();
        }
        viewLoadController = new AbortController();
        const signal = viewLoadController.signal;

        if (viewName === 'history') loadHistory(signal);
        if (viewName === 'reports') loadReports(signal);
        if (viewName === 'config') loadConfig();
    }

    // ============ 导航事件 ============
    $$('.nav-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const view = btn.dataset.view;
            if (view) switchView(view);
        });
    });

    // ============ 文件队列管理 ============
    const ALLOWED_TYPES = ['image/jpeg', 'image/png', 'image/bmp', 'image/webp', 'image/tiff', 'application/pdf'];
    const ALLOWED_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff', '.tif', '.pdf'];
    const MAX_SIZE = 50 * 1024 * 1024; // 50MB

    function addFilesToQueue(files) {
        let added = 0, skipped = 0;

        for (const file of files) {
            const ext = '.' + file.name.split('.').pop().toLowerCase();

            // 验证类型（有些浏览器文件夹上传时可能没有 type）
            const typeValid = ALLOWED_TYPES.includes(file.type) || ALLOWED_EXTENSIONS.includes(ext);
            if (!typeValid) {
                skipped++;
                continue;
            }

            if (file.size > MAX_SIZE) {
                skipped++;
                continue;
            }

            // 去重（按名称+大小）
            const exists = state.fileQueue.some(
                q => q.file.name === file.name && q.file.size === file.size
            );
            if (exists) {
                skipped++;
                continue;
            }

            state.fileQueue.push({
                file: file,
                name: file.name,
                size: file.size,
                status: 'pending',
                fileId: null,
                error: null,
                result: null,
                previewUrl: file.type.startsWith('image/') ? URL.createObjectURL(file) : null,
            });
            added++;
        }

        renderQueue();
        if (added > 0) {
            toast(`已添加 ${added} 个文件到队列` + (skipped > 0 ? ` (跳过 ${skipped} 个)` : ''), 'success');
        } else if (skipped > 0) {
            toast(`跳过了 ${skipped} 个不支持的/重复的文件`, 'warning');
        }
    }

    const QUEUE_STATUS_TEXT = {
        'pending': '等待中',
        'uploading': '上传中…',
        'processing': '识别中…',
        'uploaded': '已上传',
        'submitting': '提交中…',
        'done': '完成',
        'error': '失败',
    };
    const QUEUE_STATUS_ICON = {
        'pending': '\u23F3',
        'uploading': '\u2B06',
        'processing': '\u2699',
        'uploaded': '\u2705',
        'submitting': '\u23F3',
        'done': '\u2705',
        'error': '\u274C',
    };

    function renderQueue() {
        if (state.fileQueue.length === 0) {
            dom.fileQueueSection.style.display = 'none';
            dom.fileQueueList.innerHTML = '';
            return;
        }

        dom.fileQueueSection.style.display = 'block';
        dom.queueCount.textContent = state.fileQueue.length;

        // 差量更新：复用已存在的 DOM 节点，仅更新 class 与文本；不存在才创建
        const existing = new Map();
        dom.fileQueueList.querySelectorAll('.queue-item[data-queue-idx]').forEach(node => {
            existing.set(node.dataset.queueIdx, node);
        });

        const seen = new Set();

        state.fileQueue.forEach((item, idx) => {
            const key = String(idx);
            seen.add(key);
            const statusClass = `queue-status-${item.status}`;
            const statusText = QUEUE_STATUS_TEXT[item.status] || '';
            const statusIcon = QUEUE_STATUS_ICON[item.status] || '';

            let node = existing.get(key);
            if (!node) {
                // 创建新节点
                const safeName = escapeHtml(item.name);
                const previewHtml = item.previewUrl
                    ? `<img class="queue-preview-img" src="${escapeHtml(item.previewUrl)}" alt="${safeName}">`
                    : '';
                const wrapper = document.createElement('div');
                wrapper.innerHTML = `
                    <div class="queue-item ${statusClass}" data-queue-idx="${idx}">
                        <span class="queue-index">#${idx + 1}</span>
                        <div class="queue-preview">${previewHtml}</div>
                        <div class="queue-info">
                            <span class="queue-name" title="${safeName}">${safeName}</span>
                            <span class="queue-size">${formatFileSize(item.size)}</span>
                        </div>
                        <span class="queue-status-icon">${statusIcon}</span>
                        <span class="queue-status-text">${statusText}</span>
                    </div>`;
                node = wrapper.firstElementChild;
                dom.fileQueueList.appendChild(node);
            } else {
                // 差量更新：仅更新状态相关的 class 与文本
                node.className = `queue-item ${statusClass}`;
                const iconEl = node.querySelector('.queue-status-icon');
                if (iconEl) iconEl.textContent = statusIcon;
                const textEl = node.querySelector('.queue-status-text');
                if (textEl) textEl.textContent = statusText;

                // 更新错误信息
                let errEl = node.querySelector('.queue-error');
                if (item.error) {
                    if (!errEl) {
                        errEl = document.createElement('div');
                        errEl.className = 'queue-error';
                        node.appendChild(errEl);
                    }
                    errEl.textContent = item.error;
                } else if (errEl) {
                    errEl.remove();
                }
            }
        });

        // 移除不再存在的多余节点
        existing.forEach((node, key) => {
            if (!seen.has(key)) node.remove();
        });
    }

    function clearQueue() {
        state.fileQueue.forEach(item => {
            if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
        });
        state.fileQueue = [];
        state.batchResults = [];
        renderQueue();
        dom.previewSection.style.display = 'none';
        dom.progressSection.style.display = 'none';
        dom.resultSection.style.display = 'none';
        dom.fileInput.value = '';
        dom.folderInput.value = '';
    }

    // ============ 上传区域事件 ============
    dom.uploadZone.addEventListener('click', () => {
        if (!state.processing) dom.fileInput.click();
    });

    // 键盘访问：Enter/Space 触发上传
    dom.uploadZone.addEventListener('keydown', (e) => {
        if (state.processing) return;
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            dom.fileInput.click();
        }
    });

    // 右键点击打开文件夹选择
    dom.uploadZone.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        if (!state.processing) dom.folderInput.click();
    });

    dom.uploadZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dom.uploadZone.classList.add('drag-over');
    });

    dom.uploadZone.addEventListener('dragleave', () => {
        dom.uploadZone.classList.remove('drag-over');
    });

    dom.uploadZone.addEventListener('drop', async (e) => {
        e.preventDefault();
        dom.uploadZone.classList.remove('drag-over');

        // 递归获取所有文件（支持文件夹拖放）
        const files = await getAllFilesFromDataTransfer(e.dataTransfer);
        if (files.length > 0) {
            addFilesToQueue(files);
        }
    });

    dom.fileInput.addEventListener('change', (e) => {
        const files = Array.from(e.target.files);
        if (files.length > 0) addFilesToQueue(files);
        e.target.value = '';
    });

    dom.folderInput.addEventListener('change', (e) => {
        const files = Array.from(e.target.files);
        if (files.length > 0) {
            addFilesToQueue(files);
            toast(`已添加文件夹中的 ${files.length} 个文件`, 'success');
        }
        e.target.value = '';
    });

    // 递归获取拖放中的所有文件（包括子文件夹）
    async function getAllFilesFromDataTransfer(dataTransfer) {
        const files = [];
        const items = dataTransfer.items;

        if (items) {
            const entries = [];
            for (let i = 0; i < items.length; i++) {
                const entry = items[i].webkitGetAsEntry ? items[i].webkitGetAsEntry() : null;
                if (entry) entries.push(entry);
            }
            for (const entry of entries) {
                const entryFiles = await readEntryRecursive(entry);
                files.push(...entryFiles);
            }
        }

        // 回退：如果 items 方式不可用，使用 files
        if (files.length === 0 && dataTransfer.files) {
            for (let i = 0; i < dataTransfer.files.length; i++) {
                files.push(dataTransfer.files[i]);
            }
        }

        return files;
    }

    // 递归读取 FileSystemEntry，循环 readEntries 以处理超过 100 个条目的目录
    async function readEntryRecursive(entry) {
        const files = [];
        if (entry.isFile) {
            const file = await new Promise((resolve) => entry.file(resolve));
            files.push(file);
        } else if (entry.isDirectory) {
            const reader = entry.createReader();
            let allEntries = [];
            while (true) {
                const batch = await new Promise((resolve) => reader.readEntries(resolve));
                if (batch.length === 0) break;
                allEntries.push(...batch);
            }
            for (const childEntry of allEntries) {
                const childFiles = await readEntryRecursive(childEntry);
                files.push(...childFiles);
            }
        }
        return files;
    }

    // 清空队列按钮、处理全部按钮：见文末统一事件委托

    // ============ 批量处理（提交+轮询模式，结果按提交顺序排列） ============
    const POLL_INTERVAL_MS = 2000; // 轮询间隔 2 秒

    // 根据当前模型更新步骤标签
    function updateAnalyzeStepLabel() {
        const modelEl = $('#cfg-model');
        const labelEl = $('#step-label-analyze');
        if (modelEl && labelEl) {
            const model = modelEl.value || 'PP-StructureV3';
            if (model.startsWith('PaddleOCR-VL')) {
                labelEl.textContent = model + ' 识别';
            } else if (model === 'PP-OCRv5' || model === 'PP-OCRv4') {
                labelEl.textContent = model + ' 文字识别';
            } else {
                labelEl.textContent = model + ' 识别';
            }
        }
    }

    async function processAllFiles() {
        if (state.processing) return;
        if (state.fileQueue.length === 0) {
            toast('请先添加文件', 'warning');
            return;
        }

        state.processing = true;
        state.batchResults = [];

        // 更新步骤标签为当前模型名称
        updateAnalyzeStepLabel();

        // 隐藏结果区
        dom.resultSection.style.display = 'none';
        dom.batchResults.innerHTML = '';

        // 显示进度
        dom.progressSection.style.display = 'block';
        dom.previewSection.style.display = 'none';
        resetSteps();
        setStepActive('upload');

        const total = state.fileQueue.length;

        // ====== 阶段1: 批量上传全部文件 ======
        updateBatchProgress(0, total, '批量上传中…');

        for (let i = 0; i < state.fileQueue.length; i++) {
            const item = state.fileQueue[i];
            try {
                const result = await uploadFile(item);
                item.fileId = result.file_id;
                item.status = 'uploaded';
            } catch (err) {
                item.status = 'error';
                item.error = err.message;
            }
            updateBatchProgress(0, total, `上传: ${i + 1}/${total}`);
            renderQueue();
        }

        setStepCompleted('upload');
        setStepActive('analyze');

        // ====== 阶段2: 并发提交全部异步任务 ======
        const pendingItems = state.fileQueue.filter(item => item.status === 'uploaded');
        const pendingTotal = pendingItems.length;

        updateBatchProgress(0, total, `提交 ${pendingTotal} 个任务…`);

        // 并发提交所有任务，获取 taskId
        const submitResults = await Promise.allSettled(
            pendingItems.map(async (item) => {
                item.status = 'submitting';
                renderQueue();
                try {
                    const res = await fetch(`${API_BASE}/api/submit/${item.fileId}`, { method: 'POST' });
                    if (!res.ok) {
                        let err;
                        try { err = await res.json(); } catch { throw new Error(res.statusText || '提交失败'); }
                        throw new Error(err.detail || '提交失败');
                    }
                    const data = await res.json();
                    item.taskId = data.task_id;
                    item.status = 'processing';
                    return { item, success: true };
                } catch (err) {
                    item.status = 'error';
                    item.error = err.message;
                    return { item, success: false, error: err.message };
                }
            })
        );

        // 统计提交结果
        let submitFailed = 0;
        for (const r of submitResults) {
            if (r.status === 'rejected' || (r.value && !r.value.success)) {
                submitFailed++;
            }
        }

        setStepCompleted('upload');
        setStepActive('analyze');

        const processingItems = pendingItems.filter(item => item.taskId);
        if (processingItems.length === 0) {
            toast('所有任务提交失败', 'error');
            state.processing = false;
            showBatchResults();
            renderQueue();
            return;
        }

        // ====== 阶段3: 轮询直到所有任务完成 ======
        updateBatchProgress(0, total, `轮询 ${processingItems.length} 个任务…`);

        let allDone = false;
        let pollCount = 0;
        const maxPolls = 120; // 最大轮询 240 秒

        while (!allDone && pollCount < maxPolls) {
            pollCount++;

            // 并发轮询所有未完成的任务
            const pollResults = await Promise.allSettled(
                processingItems
                    .filter(item => item.status === 'processing')
                    .map(async (item) => {
                        try {
                            const res = await fetch(`${API_BASE}/api/poll/${item.taskId}`, { method: 'POST' });
                            const data = await res.json();
                            return { item, data };
                        } catch (err) {
                            return { item, error: err.message };
                        }
                    })
            );

            let doneCount = 0;
            for (const r of pollResults) {
                if (r.status !== 'fulfilled') continue;
                const { item, data, error } = r.value;

                if (error) {
                    item.status = 'error';
                    item.error = error;
                    doneCount++;
                    continue;
                }

                if (data.completed) {
                    doneCount++;
                    if (data.status === 'done') {
                        item.status = 'done';
                        item.result = data.result;
                    } else {
                        item.status = 'error';
                        item.error = data.error || '处理失败';
                    }
                }
            }

            // 更新进度
            const stillProcessing = processingItems.filter(item => item.status === 'processing').length;
            const completedCount = processingItems.length - stillProcessing;
            updateBatchProgress(
                completedCount, processingItems.length,
                `轮询中 ${completedCount}/${processingItems.length} (第${pollCount}轮)`
            );
            renderQueue();

            // 检查是否全部完成
            allDone = processingItems.every(item => item.status !== 'processing');

            if (!allDone) {
                await sleep(POLL_INTERVAL_MS);
            }
        }

        // 超时未完成的任务标记为错误
        for (const item of processingItems) {
            if (item.status === 'processing') {
                item.status = 'error';
                item.error = '轮询超时';
            }
        }

        setStepCompleted('analyze');
        setStepActive('report');

        // ====== 阶段4: 生成结果（按原始队列顺序） ======
        updateBatchProgress(total, total, '生成报告中…');
        dom.progressBar.style.width = '100%';

        let succeeded = 0;
        let failed = 0;

        // 按原始提交顺序排列结果
        for (const item of state.fileQueue) {
            if (item.status === 'done') {
                succeeded++;
                state.batchResults.push({
                    name: item.name,
                    fileId: item.fileId,
                    success: true,
                    processingTime: item.result?.processing_time || 0,
                    imagesCount: item.result?.images_count || 0,
                    mdLength: item.result?.markdown_text?.length || 0,
                    reportId: item.result?.report_id || '',
                    layoutItems: item.result?.layout_items || [],
                    layoutItemsCount: item.result?.layout_items_count || 0,
                });
            } else if (item.status === 'error') {
                failed++;
                state.batchResults.push({
                    name: item.name,
                    fileId: item.fileId || null,
                    success: false,
                    error: item.error || '未知错误',
                });
            }
        }

        await sleep(300);
        setStepCompleted('report');

        // 完成
        state.processing = false;
        dom.batchProgressText.textContent = '处理完成';
        dom.progressText.textContent = '全部完成';

        if (succeeded > 0 && failed === 0) {
            toast(`全部完成: ${succeeded} 个文件处理成功`, 'success');
        } else if (succeeded > 0) {
            toast(`处理完成: ${succeeded} 成功, ${failed} 失败`, 'warning');
        } else {
            toast(`全部失败: ${failed} 个文件`, 'error');
        }

        showBatchResults();
        renderQueue();
    }

    // 上传单个文件（不触发处理，仅上传）
    async function uploadFile(queueItem) {
        const file = queueItem.file;
        queueItem.status = 'uploading';
        renderQueue();

        const formData = new FormData();
        formData.append('file', file);

        const uploadRes = await fetch(`${API_BASE}/api/upload`, {
            method: 'POST',
            body: formData,
        });

        if (!uploadRes.ok) {
            let err;
            try { err = await uploadRes.json(); } catch { throw new Error(uploadRes.statusText || '上传失败'); }
            throw new Error(err.detail || '上传失败');
        }

        return await uploadRes.json();
    }

    function updateBatchProgress(current, total, text) {
        const pct = Math.round((current / total) * 100);
        dom.batchProgressText.textContent = `处理中 ${current}/${total}`;
        dom.progressBar.style.width = pct + '%';
        dom.progressText.textContent = text;
    }

    function resetSteps() {
        STEPS.forEach(step => {
            const el = document.querySelector(`[data-step="${step}"]`);
            if (el) {
                el.classList.remove('active', 'completed', 'error');
            }
        });
    }

    function setStepActive(step) {
        const el = document.querySelector(`[data-step="${step}"]`);
        if (el) el.classList.add('active');
    }

    function setStepCompleted(step) {
        const el = document.querySelector(`[data-step="${step}"]`);
        if (el) {
            el.classList.remove('active');
            el.classList.add('completed');
            el.querySelector('.step-icon').textContent = '\u2713';
        }
    }

    // ============ 结果显示 ============
    function showBatchResults() {
        dom.resultSection.style.display = 'block';
        dom.batchProgressText.textContent = `处理完成`;
        dom.progressText.textContent = '全部完成';

        const total = state.batchResults.length;
        const succeeded = state.batchResults.filter(r => r.success).length;
        const failed = total - succeeded;
        const totalTime = state.batchResults.reduce((s, r) => s + (r.processingTime || 0), 0).toFixed(1);

        dom.resultStats.innerHTML = `
            <div class="stat-item">
                <span class="stat-value">${total}</span>
                <span class="stat-label">文件总数</span>
            </div>
            <div class="stat-item">
                <span class="stat-value">${succeeded}</span>
                <span class="stat-label">成功</span>
            </div>
            <div class="stat-item">
                <span class="stat-value">${failed}</span>
                <span class="stat-label">失败</span>
            </div>
            <div class="stat-item">
                <span class="stat-value">${totalTime}s</span>
                <span class="stat-label">总耗时</span>
            </div>
        `;

        // 批量结果列表
        dom.batchResults.innerHTML = `
            <div class="batch-results-header">
                <h3>各文件处理详情</h3>
            </div>
            <div class="batch-results-list">
                ${state.batchResults.map((r, idx) => `
                    <div class="batch-result-item ${r.success ? 'result-success' : 'result-error'}">
                        <span class="batch-result-index">#${idx + 1}</span>
                        <span class="batch-result-name" title="${escapeHtml(r.name)}">${escapeHtml(r.name.length > 40 ? r.name.slice(0, 40) + '…' : r.name)}</span>
                        <span class="batch-result-status">${r.success ? '\u2705 成功' : '\u274C 失败'}</span>
                        ${r.success ? `<span class="batch-result-time">${r.processingTime}s</span>` : ''}
                        <button class="btn btn-ghost btn-sm view-file-result-btn" data-file-id="${escapeHtml(String(r.fileId || ''))}" data-name="${escapeHtml(r.name)}">查看</button>
                    </div>
                `).join('')}
            </div>
        `;

        dom.markdownPreview.style.display = 'none';
    }

    function showResult(data) {
        dom.resultSection.style.display = 'block';

        const time = data.processing_time || 0;
        const imgCount = data.images_count || 0;
        const mdLen = data.markdown_text ? data.markdown_text.length : 0;
        const layoutCount = data.layout_items_count || 0;
        // 从 Markdown 文本中估算题目数量（匹配以数字加点的题号格式，如 "1."、"2."）
        const questionCount = data.markdown_text ? (data.markdown_text.match(/^\d+\./gm) || []).length : 0;
        dom.resultStats.innerHTML = `
            <div class="stat-item">
                <span class="stat-value">${time}s</span>
                <span class="stat-label">处理耗时</span>
            </div>
            <div class="stat-item">
                <span class="stat-value">${imgCount}</span>
                <span class="stat-label">识别图片</span>
            </div>
            <div class="stat-item">
                <span class="stat-value">${layoutCount}</span>
                <span class="stat-label">版面区域</span>
            </div>
            <div class="stat-item">
                <span class="stat-value">${questionCount}</span>
                <span class="stat-label">题目数量</span>
            </div>
            <div class="stat-item">
                <span class="stat-value">${mdLen}</span>
                <span class="stat-label">文本字符</span>
            </div>
            <div class="stat-item">
                <span class="stat-value">${data.success ? '成功' : '失败'}</span>
                <span class="stat-label">处理状态</span>
            </div>
        `;

        // 版面分析区域
        const layoutItems = data.layout_items || [];
        const layoutSection = $('#layout-analysis');
        if (layoutSection && layoutItems.length > 0) {
            const layoutTypeLabels = {
                'text': '正文文本',
                'title': '标题',
                'table': '表格',
                'figure': '图片',
                'formula': '公式',
                'header': '页眉',
                'footer': '页脚',
                'reference': '引用/参考文献',
                'code': '代码块',
                'chart': '图表',
            };
            layoutSection.innerHTML = `
                <h3>版面分析 (<span>${layoutItems.length}个区域</span>)</h3>
                <div class="layout-items-list">
                    ${layoutItems.map((item, i) => {
                        const rawType = item.type || 'unknown';
                        const safeType = escapeHtml(rawType);
                        const label = layoutTypeLabels[item.type] || rawType || '未分类';
                        const safeLabel = escapeHtml(label);
                        const preview = item.content_preview
                            ? `<div class="layout-item-content">${escapeHtml(item.content_preview)}</div>`
                            : '';
                        return `
                        <div class="layout-item layout-type-${safeType}">
                            <div class="layout-item-header">
                                <span class="layout-item-index">#${i + 1}</span>
                                <span class="layout-item-type">${safeLabel}</span>
                                <span class="layout-item-type-en">(${safeType})</span>
                            </div>
                            ${preview}
                        </div>
                        `;
                    }).join('')}
                </div>
            `;
            layoutSection.style.display = 'block';
        } else if (layoutSection) {
            layoutSection.style.display = 'none';
        }

        if (data.markdown_text) {
            dom.markdownPreview.style.display = 'block';
            if (window.MathJax && window.MathJax.typesetClear) {
                window.MathJax.typesetClear([dom.mdContent]);
            }
            // 后端直接返回 report_id（目录名），无需从路径提取
            const reportId = data.report_id || null;
            dom.mdContent.innerHTML = renderMarkdown(data.markdown_text, reportId);
            if (window.MathJax && window.MathJax.typesetPromise) {
                window.MathJax.typesetPromise([dom.mdContent]).catch((err) => console.error('MathJax typeset error:', err));
            }
        } else {
            dom.markdownPreview.style.display = 'none';
        }

        if (data.error) {
            toast('处理警告: ' + data.error, 'warning');
        }
    }

    function escapeHtml(str) {
        if (str == null) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function renderMarkdown(md, reportId) {
        // 解析图片路径：如果提供了 reportId，将相对路径映射到 API 端点
        function resolveImagePath(src) {
            if (!src || src.startsWith('http://') || src.startsWith('https://') || src.startsWith('data:')) {
                return src;
            }
            if (reportId) {
                // 去掉可能的前导 ./ 或多余的 imgs/ 前缀（统一由 API 处理）
                let cleanSrc = src.replace(/^\.\//, '');
                return `${API_BASE}/api/report/${reportId}/image/${encodeURI(cleanSrc)}`;
            }
            return src;
        }

        // XSS 防护：移除 script 标签、事件处理器（含无引号/单引号/双引号）和 javascript: 协议
        let sanitized = md
            .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
            .replace(/\son\w+\s*=\s*"[^"]*"/gi, '')
            .replace(/\son\w+\s*=\s*'[^']*'/gi, '')
            .replace(/\son\w+\s*=\s*[^\s>]+/gi, '')
            .replace(/javascript:/gi, '');

        let html = sanitized
            // 先处理 HTML img 标签（PP-StructureV3 输出中可能包含）
            .replace(/<img\s+src="([^"]+)"(?:\s+alt="([^"]*)")?[^>]*\/?>/gi,
                (match, src, alt) => `<img src="${escapeHtml(resolveImagePath(src))}" alt="${escapeHtml(alt || '')}" width="100%">`)
            // Markdown 图片 ![alt](src)
            .replace(/!\[([^\]]*)\]\(([^)]+)\)/g,
                (match, alt, src) => `<img src="${escapeHtml(resolveImagePath(src))}" alt="${escapeHtml(alt || '')}" width="100%">`)
            .replace(/^### (.+)$/gm, (m, p1) => `<h3>${escapeHtml(p1)}</h3>`)
            .replace(/^## (.+)$/gm, (m, p1) => `<h2>${escapeHtml(p1)}</h2>`)
            .replace(/^# (.+)$/gm, (m, p1) => `<h1>${escapeHtml(p1)}</h1>`)
            .replace(/\*\*(.+?)\*\*/g, (m, p1) => `<strong>${escapeHtml(p1)}</strong>`)
            .replace(/\*(.+?)\*/g, (m, p1) => `<em>${escapeHtml(p1)}</em>`)
            .replace(/`([^`]+)`/g, (m, p1) => `<code>${escapeHtml(p1)}</code>`)
            .replace(/```json\n([\s\S]*?)```/g, (m, p1) => `<pre><code>${escapeHtml(p1)}</code></pre>`)
            .replace(/^- (.+)$/gm, (m, p1) => `<li>${escapeHtml(p1)}</li>`)
            .replace(/^\|(.+)\|$/gm, (match) => {
                const cells = match.split('|').filter(c => c.trim());
                const isHeader = match.includes('---');
                if (isHeader) return '';
                return '<tr>' + cells.map(c => `<td>${escapeHtml(c.trim())}</td>`).join('') + '</tr>';
            })
            .replace(/^> (.+)$/gm, (m, p1) => `<blockquote>${escapeHtml(p1)}</blockquote>`)
            .replace(/^---$/gm, '<hr>');

        return html;
    }

    function sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    // ============ 结果操作按钮：见文末统一事件委托 ============

    async function viewFileResult(fileId, name) {
        // 从队列中查找结果
        const queueItem = state.fileQueue.find(q => q.fileId === fileId);
        if (queueItem && queueItem.result) {
            showResult(queueItem.result);
            dom.previewOriginal.src = queueItem.previewUrl || '';
            dom.previewSection.style.display = 'block';
            window.scrollTo({ top: dom.resultSection.offsetTop - 80, behavior: 'smooth' });
        }
    }

    async function downloadAllReports() {
        const successResults = state.batchResults.filter(r => r.success);
        if (successResults.length === 0) {
            toast('没有可下载的报告', 'warning');
            return;
        }

        // 收集所有 report_id
        const reportIds = successResults
            .map(r => r.reportId || '')
            .filter(id => id);

        if (reportIds.length === 0) {
            toast('没有已保存的报告', 'warning');
            return;
        }

        try {
            const res = await fetch(`${API_BASE}/api/batch/download`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ report_ids: reportIds }),
            });
            if (!res.ok) {
                let err;
                try { err = await res.json(); } catch { throw new Error(res.statusText || '下载失败'); }
                throw new Error(err.detail || '下载失败');
            }
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'batch_reports.zip';
            a.click();
            URL.revokeObjectURL(url);
            toast(`已打包下载 ${reportIds.length} 份报告`, 'success');
        } catch (e) {
            toast('批量下载失败: ' + e.message, 'error');
        }
    }

    async function downloadLayoutReport() {
        const successResults = state.batchResults.filter(r => r.success);
        if (successResults.length === 0) {
            toast('没有可下载的版面分析报告', 'warning');
            return;
        }

        // 筛选有版面分析数据的文件
        const files = successResults
            .filter(r => r.layoutItems && r.layoutItems.length > 0)
            .map(r => ({
                filename: r.name,
                layout_items: r.layoutItems,
                processing_time: r.processingTime,
            }));

        if (files.length === 0) {
            toast('没有可用的版面分析数据', 'warning');
            return;
        }

        try {
            const res = await fetch(`${API_BASE}/api/batch/download-layout`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ files }),
            });
            if (!res.ok) {
                let err;
                try { err = await res.json(); } catch { throw new Error(res.statusText || '下载失败'); }
                throw new Error(err.detail || '下载失败');
            }
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'batch_layout_report.md';
            a.click();
            URL.revokeObjectURL(url);
            toast('版面分析报告已下载', 'success');
        } catch (e) {
            toast('版面报告下载失败: ' + e.message, 'error');
        }
    }

    // ============ 历史记录 ============
    async function loadHistory(signal) {
        try {
            const res = await fetch(`${API_BASE}/api/history?limit=50`, { signal });
            if (!res.ok) {
                throw new Error(res.statusText || '加载历史记录失败');
            }
            const data = await res.json();

            if (data.items.length === 0) {
                dom.historyTbody.innerHTML = `
                    <tr><td colspan="7" class="empty-row">暂无处理记录</td></tr>`;
                return;
            }

            dom.historyTbody.innerHTML = data.items.map(item => `
                <tr>
                    <td><span class="report-id">#${escapeHtml(item.id)}</span></td>
                    <td title="${escapeHtml(item.filename)}">${escapeHtml(item.filename.length > 25 ? item.filename.slice(0, 25) + '…' : item.filename)}</td>
                    <td>${formatTime(item.timestamp)}</td>
                    <td>
                        <span class="badge ${item.success ? 'badge-success' : 'badge-error'}">
                            ${item.success ? '成功' : '失败'}
                        </span>
                    </td>
                    <td>${item.processing_time || 0}s</td>
                    <td>${item.images_count || 0}</td>
                    <td>
                        <button class="btn btn-ghost btn-sm view-report-btn" data-report-id="${escapeHtml(item.report_id || '')}">
                            查看
                        </button>
                    </td>
                </tr>
            `).join('');

        } catch (error) {
            if (error.name === 'AbortError') return;
            console.error('加载历史记录失败:', error);
            toast('加载历史记录失败', 'error');
            dom.historyTbody.innerHTML = `
                <tr><td colspan="7" class="empty-row">加载失败</td></tr>`;
        }
    }

    // ============ 报告中心 ============
    const selectedReportIds = new Set();

    function _refreshBatchDeleteBtn() {
        const count = selectedReportIds.size;
        const btn = $('#btn-batch-delete-reports');
        if (btn) {
            btn.disabled = count === 0;
            btn.textContent = count > 0 ? `批量删除 (${count})` : '批量删除';
        }
        const cb = $('#reports-select-all');
        if (cb) {
            const total = document.querySelectorAll('.report-card').length;
            cb.checked = total > 0 && count === total;
        }
    }

    async function loadReports(signal) {
        try {
            const res = await fetch(`${API_BASE}/api/reports?limit=50`, { signal });
            if (!res.ok) {
                throw new Error(res.statusText || '加载报告列表失败');
            }
            const data = await res.json();

            if (data.reports.length === 0) {
                dom.reportsGrid.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-icon" aria-hidden="true">&#128196;</div>
                        <p>暂无生成的报告</p>
                    </div>`;
                selectedReportIds.clear();
                _refreshBatchDeleteBtn();
                return;
            }

            dom.reportsGrid.innerHTML = data.reports.map(r => `
                <div class="report-card" data-report-id="${escapeHtml(r.id)}">
                    <div class="report-card-header">
                        <label class="report-select-label" aria-label="选择报告 ${escapeHtml(r.id)}">
                            <input type="checkbox" class="report-select-cb" data-report-id="${escapeHtml(r.id)}"
                                ${selectedReportIds.has(r.id) ? 'checked' : ''}>
                        </label>
                        <span class="report-id">#${escapeHtml(r.id)}</span>
                        <span class="report-date">${formatTime(r.created_time)}</span>
                    </div>
                    <div class="report-actions">
                        <button class="btn btn-secondary btn-sm view-report-btn" data-report-id="${escapeHtml(r.id)}">查看详情</button>
                        <button class="btn btn-ghost btn-sm download-report-btn" data-report-id="${escapeHtml(r.id)}">下载</button>
                        <button class="btn btn-ghost btn-sm delete-report-btn" data-report-id="${escapeHtml(r.id)}" style="color:var(--error)">删除</button>
                    </div>
                </div>
            `).join('');

            _refreshBatchDeleteBtn();

        } catch (error) {
            if (error.name === 'AbortError') return;
            console.error('加载报告列表失败:', error);
            toast('加载报告列表失败', 'error');
        }
    }

    // 报告操作（事件委托）：见文末统一事件委托

    async function viewReport(reportId) {
        try {
            const res = await fetch(`${API_BASE}/api/report/${encodeURIComponent(reportId)}`);
            const data = await res.json();
            if (window.MathJax && window.MathJax.typesetClear) {
                window.MathJax.typesetClear([dom.mdContent]);
            }
            dom.mdContent.innerHTML = renderMarkdown(data.content, reportId);
            dom.markdownPreview.style.display = 'block';
            if (window.MathJax && window.MathJax.typesetPromise) {
                window.MathJax.typesetPromise([dom.mdContent]).catch((err) => console.error('MathJax typeset error:', err));
            }
            dom.resultSection.style.display = 'block';
            dom.batchResults.innerHTML = '';
            dom.resultStats.innerHTML = `<div class="stat-item"><span class="stat-value">#${escapeHtml(reportId || '')}</span><span class="stat-label">报告编号</span></div>`;
            switchView('upload');
            window.scrollTo({ top: dom.resultSection.offsetTop - 80, behavior: 'smooth' });
        } catch (error) {
            toast('加载报告失败', 'error');
        }
    }

    async function downloadReportById(reportId) {
        try {
            const res = await fetch(`${API_BASE}/api/report/${encodeURIComponent(reportId)}/download`);
            if (!res.ok) {
                toast('下载失败', 'error');
                return;
            }
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `report_${reportId}.zip`;
            a.click();
            URL.revokeObjectURL(url);
            toast('报告已下载（解压后用 Typora 打开 report.md 即可查看）', 'success');
        } catch (error) {
            toast('下载失败', 'error');
        }
    }

    async function deleteReport(reportId) {
        try {
            const res = await fetch(`${API_BASE}/api/report/${encodeURIComponent(reportId)}`, { method: 'DELETE' });
            if (!res.ok) {
                throw new Error(res.statusText || '删除失败');
            }
            const data = await res.json();
            if (data.success) {
                toast('报告已删除', 'success');
                loadReports();
            } else {
                toast('删除失败', 'error');
            }
        } catch (error) {
            toast('删除失败', 'error');
        }
    }

    // ============ 系统配置 ============
    async function loadConfig() {
        try {
            const res = await fetch(`${API_BASE}/api/config`);
            if (!res.ok) {
                throw new Error(res.statusText || '加载配置失败');
            }
            const config = await res.json();

            $('#cfg-api-url').value = config.paddleocr_api_url || '';
            $('#cfg-host').value = config.host || '127.0.0.1';
            $('#cfg-port').value = config.port || 8500;
            $('#cfg-model').value = config.paddleocr_model || 'PP-StructureV3';
            $('#cfg-max-size').value = config.max_upload_size_mb || 50;
            $('#cfg-upload-dir').value = config.upload_dir || './uploads';
            $('#cfg-output-dir').value = config.output_dir || './output';
            $('#cfg-log-level').value = config.log_level || 'INFO';

            if (config.api_key_configured) {
                $('#cfg-api-key').placeholder = config.api_key_prefix + ' (已配置)';
            }
        } catch (error) {
            console.error('加载配置失败:', error);
            toast('加载配置失败', 'error');
        }
    }

    // 配置保存按钮：见文末统一事件委托

    async function saveConfig(data, name) {
        try {
            const res = await fetch(`${API_BASE}/api/config`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            });
            if (!res.ok) {
                throw new Error(res.statusText || `${name}保存失败`);
            }
            const result = await res.json();
            if (result.success) {
                toast(`${name}已保存 (${result.updated_fields.length}项)`, 'success');
            } else {
                toast(`${name}保存失败`, 'error');
            }
        } catch (error) {
            toast(`${name}保存失败`, 'error');
        }
    }

    async function testApiConnection() {
        toast('正在测试API连接…', 'info');
        try {
            const res = await fetch(`${API_BASE}/api/health`);
            const data = await res.json();
            if (data.status === 'healthy') {
                toast('API服务连接正常', 'success');
            } else {
                toast('API服务响应异常', 'warning');
            }
        } catch (error) {
            toast('API服务连接失败', 'error');
        }
    }

    // ============ 统一事件委托（合并原 5 个全局 click 监听器） ============
    document.addEventListener('click', async (e) => {
        // --- 队列操作 ---
        if (e.target.id === 'btn-clear-queue') {
            clearQueue();
        }
        if (e.target.id === 'btn-process-all') {
            processAllFiles();
        }

        // --- 结果操作 ---
        if (e.target.id === 'btn-download-all-reports') {
            downloadAllReports();
        }
        if (e.target.id === 'btn-download-layout-report') {
            downloadLayoutReport();
        }
        if (e.target.id === 'btn-view-report') {
            switchView('reports');
        }
        if (e.target.id === 'btn-retry') {
            clearQueue();
        }

        const viewFileBtn = e.target.closest('.view-file-result-btn');
        if (viewFileBtn) {
            const fileId = viewFileBtn.dataset.fileId;
            const name = viewFileBtn.dataset.name;
            if (fileId) await viewFileResult(fileId, name);
        }

        // --- 报告操作 ---
        const reportBtn = e.target.closest('.view-report-btn');
        const downloadBtn = e.target.closest('.download-report-btn');
        const deleteBtn = e.target.closest('.delete-report-btn');
        const selectCb = e.target.closest('.report-select-cb');
        const selectAllCb = e.target.closest('#reports-select-all');
        const batchDelBtn = e.target.closest('#btn-batch-delete-reports');

        if (selectCb) {
            const rid = selectCb.dataset.reportId;
            if (selectCb.checked) {
                selectedReportIds.add(rid);
            } else {
                selectedReportIds.delete(rid);
            }
            _refreshBatchDeleteBtn();
            return;
        }

        if (selectAllCb) {
            const allCbs = document.querySelectorAll('.report-select-cb');
            if (selectAllCb.checked) {
                allCbs.forEach(cb => {
                    selectedReportIds.add(cb.dataset.reportId);
                    cb.checked = true;
                });
            } else {
                allCbs.forEach(cb => {
                    selectedReportIds.delete(cb.dataset.reportId);
                    cb.checked = false;
                });
            }
            _refreshBatchDeleteBtn();
            return;
        }

        if (batchDelBtn) {
            if (selectedReportIds.size === 0) return;
            const ids = Array.from(selectedReportIds);
            const confirmMsg = `确认删除选中的 ${ids.length} 个报告？\n\n`
                + ids.slice(0, 5).map(id => `  - ${id}`).join('\n')
                + (ids.length > 5 ? `\n  … 等 ${ids.length} 项` : '')
                + '\n\n此操作不可撤销。';
            if (!confirm(confirmMsg)) return;

            try {
                toast('正在批量删除…', 'info');
                const res = await fetch(`${API_BASE}/api/reports/batch-delete`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ids }),
                });
                if (!res.ok) {
                    throw new Error(res.statusText || '批量删除失败');
                }
                let data;
                try {
                    data = await res.json();
                } catch {
                    throw new Error(res.statusText || '批量删除失败');
                }
                if (data.success) {
                    toast(`已删除 ${data.deleted} 个报告${data.failed > 0 ? `，失败 ${data.failed} 个` : ''}`, 'success');
                    selectedReportIds.clear();
                    loadReports();
                } else {
                    toast('批量删除失败', 'error');
                }
            } catch (error) {
                toast('批量删除失败', 'error');
            }
            return;
        }

        if (reportBtn) {
            const reportId = reportBtn.dataset.reportId;
            if (reportId) viewReport(reportId);
        }

        if (downloadBtn) {
            const reportId = downloadBtn.dataset.reportId;
            if (reportId) downloadReportById(reportId);
        }

        if (deleteBtn) {
            const reportId = deleteBtn.dataset.reportId;
            if (reportId && confirm('确认删除此报告？')) {
                deleteReport(reportId);
            }
        }

        // --- 配置保存 ---
        if (e.target.id === 'btn-save-api-config') {
            const data = {
                paddleocr_api_url: $('#cfg-api-url').value,
                paddleocr_api_key: $('#cfg-api-key').value || undefined,
                paddleocr_model: $('#cfg-model').value,
            };
            await saveConfig(data, 'API配置');
        }

        if (e.target.id === 'btn-save-server-config') {
            const data = {
                host: $('#cfg-host').value,
                port: parseInt($('#cfg-port').value),
                upload_dir: $('#cfg-upload-dir').value,
                output_dir: $('#cfg-output-dir').value,
                max_upload_size_mb: parseInt($('#cfg-max-size').value),
            };
            await saveConfig(data, '服务器配置');
        }

        if (e.target.id === 'btn-save-process-config') {
            const data = {
                log_level: $('#cfg-log-level').value,
            };
            await saveConfig(data, '处理参数');
        }

        if (e.target.id === 'btn-test-api') {
            await testApiConnection();
        }

        // --- 刷新按钮 ---
        if (e.target.id === 'btn-refresh-history') loadHistory();
        if (e.target.id === 'btn-refresh-reports') loadReports();
    });

    // ============ 服务器状态检测 ============
    async function checkServerStatus() {
        try {
            const res = await fetch(`${API_BASE}/api/health`);
            const data = await res.json();
            if (data.status === 'healthy') {
                state.serverConnected = true;
                dom.statusDot.className = 'status-dot connected';
                dom.statusText.textContent = '服务正常';
            } else {
                state.serverConnected = false;
                dom.statusDot.className = 'status-dot disconnected';
                dom.statusText.textContent = '服务异常';
            }
        } catch {
            state.serverConnected = false;
            dom.statusDot.className = 'status-dot disconnected';
            dom.statusText.textContent = '连接断开';
        }
    }

    // ============ 初始化 ============
    function init() {
        initParticles();
        checkServerStatus();
        setInterval(checkServerStatus, 30000);

        // 处理中离开页面时警告
        window.addEventListener('beforeunload', (e) => {
            if (state.processing) {
                e.preventDefault();
                e.returnValue = '正在处理文件，确定要离开吗？';
                return e.returnValue;
            }
        });

        if (state.currentView === 'history') loadHistory();
        if (state.currentView === 'reports') loadReports();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
