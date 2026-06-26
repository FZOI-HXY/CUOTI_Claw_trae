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
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
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
        const canvas = $('#particles-canvas');
        const ctx = canvas.getContext('2d');
        let particles = [];
        let animId;

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
            animId = requestAnimationFrame(animate);
        }

        resize();
        createParticles();
        animate();
        window.addEventListener('resize', () => { resize(); createParticles(); });
    }

    // ============ 视图切换 ============
    function switchView(viewName) {
        state.currentView = viewName;
        $$('.view-panel').forEach(p => p.classList.remove('active'));
        $$('.nav-btn').forEach(b => b.classList.remove('active'));

        const panel = $(`#view-${viewName}`);
        const btn = document.querySelector(`[data-view="${viewName}"]`);

        if (panel) panel.classList.add('active');
        if (btn) btn.classList.add('active');

        if (viewName === 'history') loadHistory();
        if (viewName === 'reports') loadReports();
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
    const ALLOWED_TYPES = ['image/jpeg', 'image/png', 'image/bmp', 'image/webp', 'image/tiff'];
    const ALLOWED_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff', '.tif'];
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

    function renderQueue() {
        if (state.fileQueue.length === 0) {
            dom.fileQueueSection.style.display = 'none';
            return;
        }

        dom.fileQueueSection.style.display = 'block';
        dom.queueCount.textContent = state.fileQueue.length;

        dom.fileQueueList.innerHTML = state.fileQueue.map((item, idx) => {
            const statusClass = `queue-status-${item.status}`;
            const statusText = {
                'pending': '等待中',
                'uploading': '上传中...',
                'processing': '识别中...',
                'done': '完成',
                'error': '失败',
            }[item.status] || '';

            const statusIcon = {
                'pending': '\u23F3',
                'uploading': '\u2B06',
                'processing': '\u2699',
                'done': '\u2705',
                'error': '\u274C',
            }[item.status] || '';

            const safeName = escapeHtml(item.name);
            const previewHtml = item.previewUrl
                ? `<img class="queue-preview-img" src="${escapeHtml(item.previewUrl)}" alt="${safeName}">`
                : '';

            const errorHtml = item.error
                ? `<div class="queue-error">${escapeHtml(item.error)}</div>`
                : '';

            return `
                <div class="queue-item ${statusClass}">
                    <span class="queue-index">#${idx + 1}</span>
                    <div class="queue-preview">${previewHtml}</div>
                    <div class="queue-info">
                        <span class="queue-name" title="${safeName}">${safeName}</span>
                        <span class="queue-size">${formatFileSize(item.size)}</span>
                    </div>
                    <span class="queue-status-icon">${statusIcon}</span>
                    <span class="queue-status-text">${statusText}</span>
                    ${errorHtml}
                </div>
            `;
        }).join('');
    }

    function clearQueue() {
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

    // 清空队列按钮
    document.addEventListener('click', (e) => {
        if (e.target.id === 'btn-clear-queue') {
            clearQueue();
        }
        if (e.target.id === 'btn-process-all') {
            processAllFiles();
        }
    });

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
        updateBatchProgress(0, total, '批量上传中...');

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

        updateBatchProgress(0, total, `提交 ${pendingTotal} 个任务...`);

        // 并发提交所有任务，获取 taskId
        const submitResults = await Promise.allSettled(
            pendingItems.map(async (item) => {
                item.status = 'submitting';
                renderQueue();
                try {
                    const res = await fetch(`${API_BASE}/api/submit/${item.fileId}`, { method: 'POST' });
                    if (!res.ok) {
                        const err = await res.json();
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
        updateBatchProgress(0, total, `轮询 ${processingItems.length} 个任务...`);

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
            dom.progressBar.style.width = Math.round((completedCount / processingItems.length) * 90 + 5) + '%';
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
        updateBatchProgress(total, total, '生成报告中...');
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
                    reportDir: item.result?.report_dir || '',
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
            const err = await uploadRes.json();
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

    function updateProgress(percent, text) {
        dom.progressBar.style.width = percent + '%';
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
                        <span class="batch-result-name" title="${escapeHtml(r.name)}">${escapeHtml(r.name.length > 40 ? r.name.slice(0, 40) + '...' : r.name)}</span>
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
                        const label = layoutTypeLabels[item.type] || item.type || '未分类';
                        const preview = item.content_preview
                            ? `<div class="layout-item-content">${escapeHtml(item.content_preview)}</div>`
                            : '';
                        return `
                        <div class="layout-item layout-type-${item.type || 'unknown'}">
                            <div class="layout-item-header">
                                <span class="layout-item-index">#${i + 1}</span>
                                <span class="layout-item-type">${label}</span>
                                <span class="layout-item-type-en">(${item.type || 'unknown'})</span>
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
            // 从 report_dir 提取 report_id（如 "c:\...\20260609_112608" → "20260609_112608"）
            const reportId = data.report_dir ? data.report_dir.split(/[\\/]/).pop() : null;
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
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
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

        // XSS 防护：移除 script 标签、事件处理器和 javascript: 协议
        let sanitized = md
            .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
            .replace(/\son\w+\s*=\s*"[^"]*"/gi, '')
            .replace(/\son\w+\s*=\s*'[^']*'/gi, '')
            .replace(/javascript:/gi, '');

        let html = sanitized
            // 先处理 HTML img 标签（PP-StructureV3 输出中可能包含）
            .replace(/<img\s+src="([^"]+)"(?:\s+alt="([^"]*)")?[^>]*\/?>/gi,
                (match, src, alt) => `<img src="${resolveImagePath(src)}" alt="${alt || ''}">`)
            // Markdown 图片 ![alt](src)
            .replace(/!\[([^\]]*)\]\(([^)]+)\)/g,
                (match, alt, src) => `<img src="${resolveImagePath(src)}" alt="${alt || ''}">`)
            .replace(/^### (.+)$/gm, '<h3>$1</h3>')
            .replace(/^## (.+)$/gm, '<h2>$1</h2>')
            .replace(/^# (.+)$/gm, '<h1>$1</h1>')
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.+?)\*/g, '<em>$1</em>')
            .replace(/`([^`]+)`/g, '<code>$1</code>')
            .replace(/```json\n([\s\S]*?)```/g, '<pre><code>$1</code></pre>')
            .replace(/^- (.+)$/gm, '<li>$1</li>')
            .replace(/^\|(.+)\|$/gm, (match) => {
                const cells = match.split('|').filter(c => c.trim());
                const isHeader = match.includes('---');
                if (isHeader) return '';
                return '<tr>' + cells.map(c => `<td>${c.trim()}</td>`).join('') + '</tr>';
            })
            .replace(/^> (.+)$/gm, '<blockquote>$1</blockquote>')
            .replace(/^---$/gm, '<hr>');

        return html;
    }

    function sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    // ============ 结果操作按钮 ============
    document.addEventListener('click', async (e) => {
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

        // 查看单个文件结果
        const viewFileBtn = e.target.closest('.view-file-result-btn');
        if (viewFileBtn) {
            const fileId = viewFileBtn.dataset.fileId;
            const name = viewFileBtn.dataset.name;
            if (fileId) await viewFileResult(fileId, name);
        }
    });

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
            .map(r => {
                const reportDir = r.reportDir || '';
                return reportDir.split(/[\\/]/).pop();
            })
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
                const err = await res.json();
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
                const err = await res.json();
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
    async function loadHistory() {
        try {
            const res = await fetch(`${API_BASE}/api/history?limit=50`);
            const data = await res.json();

            if (data.items.length === 0) {
                dom.historyTbody.innerHTML = `
                    <tr><td colspan="7" class="empty-row">暂无处理记录</td></tr>`;
                return;
            }

            dom.historyTbody.innerHTML = data.items.map(item => `
                <tr>
                    <td><span class="report-id">#${escapeHtml(item.id)}</span></td>
                    <td title="${escapeHtml(item.filename)}">${escapeHtml(item.filename.length > 25 ? item.filename.slice(0, 25) + '...' : item.filename)}</td>
                    <td>${formatTime(item.timestamp)}</td>
                    <td>
                        <span class="badge ${item.success ? 'badge-success' : 'badge-error'}">
                            ${item.success ? '成功' : '失败'}
                        </span>
                    </td>
                    <td>${item.processing_time || 0}s</td>
                    <td>${item.images_count || 0}</td>
                    <td>
                        <button class="btn btn-ghost btn-sm view-report-btn" data-report-id="${escapeHtml(item.report_dir ? item.report_dir.split('/').pop().split('\\').pop() : '')}">
                            查看
                        </button>
                    </td>
                </tr>
            `).join('');

        } catch (error) {
            console.error('加载历史记录失败:', error);
            dom.historyTbody.innerHTML = `
                <tr><td colspan="7" class="empty-row">加载失败</td></tr>`;
        }
    }

    // ============ 报告中心 ============
    async function loadReports() {
        try {
            const res = await fetch(`${API_BASE}/api/reports?limit=50`);
            const data = await res.json();

            if (data.reports.length === 0) {
                dom.reportsGrid.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-icon">&#128196;</div>
                        <p>暂无生成的报告</p>
                    </div>`;
                return;
            }

            dom.reportsGrid.innerHTML = data.reports.map(r => `
                <div class="report-card" data-report-id="${escapeHtml(r.id)}">
                    <div class="report-card-header">
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

        } catch (error) {
            console.error('加载报告列表失败:', error);
        }
    }

    // 报告操作（事件委托）
    document.addEventListener('click', async (e) => {
        const reportBtn = e.target.closest('.view-report-btn');
        const downloadBtn = e.target.closest('.download-report-btn');
        const deleteBtn = e.target.closest('.delete-report-btn');

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
    });

    async function viewReport(reportId) {
        try {
            const res = await fetch(`${API_BASE}/api/report/${reportId}`);
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
            const res = await fetch(`${API_BASE}/api/report/${reportId}/download`);
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
            const res = await fetch(`${API_BASE}/api/report/${reportId}`, { method: 'DELETE' });
            const data = await res.json();
            if (data.success) {
                toast('报告已删除', 'success');
                loadReports();
            }
        } catch (error) {
            toast('删除失败', 'error');
        }
    }

    // ============ 系统配置 ============
    async function loadConfig() {
        try {
            const res = await fetch(`${API_BASE}/api/config`);
            const config = await res.json();

            $('#cfg-api-url').value = config.paddleocr_api_url || '';
            $('#cfg-host').value = config.host || '0.0.0.0';
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
        }
    }

    // 配置保存按钮
    document.addEventListener('click', async (e) => {
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
    });

    async function saveConfig(data, name) {
        try {
            const res = await fetch(`${API_BASE}/api/config`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            });
            const result = await res.json();
            if (result.success) {
                toast(`${name}已保存 (${result.updated_fields.length}项)`, 'success');
            }
        } catch (error) {
            toast(`${name}保存失败`, 'error');
        }
    }

    async function testApiConnection() {
        toast('正在测试API连接...', 'info');
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

    // ============ 刷新按钮 ============
    document.addEventListener('click', (e) => {
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

        if (state.currentView === 'history') loadHistory();
        if (state.currentView === 'reports') loadReports();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
