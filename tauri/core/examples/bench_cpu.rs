//! 纯 CPU 本地模型基准：测量 bge-small-zh-v1.5 嵌入 & bge-reranker-base 重排的
//! 加载耗时、单条/批量推理耗时与峰值内存。
//! 用法: cargo run -p cuoti-core --example bench_cpu

use std::time::Instant;

use cuoti_core::embedder::{local_embedder, local_reranker, Embedder, Reranker};

fn main() {
    // 预热样本：模拟真实错题文本（标题+选项+解析），中文为主
    let samples: Vec<String> = (0..20)
        .map(|i| {
            format!(
                "已知函数 f(x)=ax^2+bx+c 的图象经过点(1,2)，且当 x=2 时取得最小值 -1，求 a,b,c 的值。\
                 选项 A. a=3,b=-12,c=11  B. a=1,b=-4,c=3  C. a=2,b=-8,c=5。\
                 解析：由顶点式 f(x)=a(x-{0})^2 得，代入 (1,2) 即可求出 a，再展开得 b、c。",
                i
            )
        })
        .collect();

    // 调试：确认缓存环境与目录
    println!("HF_HOME={:?}", std::env::var("HF_HOME").ok());
    println!("FASTEMBED_CACHE_DIR={:?}", std::env::var("FASTEMBED_CACHE_DIR").ok());
    let hf_home = std::env::var("HF_HOME").unwrap_or_else(|_| ".fastembed_cache".into());
    let repo = format!("{}/models--Xenova--bge-small-zh-v1.5", hf_home);
    println!("repo_dir={}", repo);
    let onnx = format!("{}/snapshots/abc123/onnx/model.onnx", repo);
    println!("onnx_exists={}", std::path::Path::new(&onnx).exists());

    // ---- 嵌入模型加载 ----
    let t0 = Instant::now();
    let rt = tokio::runtime::Runtime::new().unwrap();
    let embedder = rt.block_on(local_embedder()).expect("load embedder");
    let load_embed = t0.elapsed();
    println!(
        "[嵌入] 模型加载耗时: {:.2}s, 维度: {}",
        load_embed.as_secs_f64(),
        embedder.dim()
    );

    // ---- 单条嵌入（对应实时问答 query 编码）----
    let texts1 = vec![samples[0].clone()];
    let t1 = Instant::now();
    rt.block_on(embedder.embed(&texts1)).expect("embed single");
    let single = t1.elapsed();
    println!("[嵌入] 单条推理(实时 query): {:.1}ms", single.as_secs_f64() * 1000.0);

    // ---- 批量嵌入（对应建索引/增量索引）----
    let t2 = Instant::now();
    rt.block_on(embedder.embed(&samples)).expect("embed batch");
    let batch = t2.elapsed();
    println!(
        "[嵌入] 批量{}条推理: {:.1}ms, 单条均值 {:.1}ms",
        samples.len(),
        batch.as_secs_f64() * 1000.0,
        batch.as_secs_f64() * 1000.0 / samples.len() as f64
    );

    // ---- 重排模型加载 ----
    let t3 = Instant::now();
    let reranker = rt.block_on(local_reranker()).expect("load reranker");
    let load_rerank = t3.elapsed();
    println!("[重排] 模型加载耗时: {:.2}s", load_rerank.as_secs_f64());

    // ---- 重排推理（对应 top_k 候选精排，通常 5~20 条）----
    let query = &samples[0];
    for k in [5usize, 10, 20] {
        let docs: Vec<String> = samples[..k].to_vec();
        let t4 = Instant::now();
        rt.block_on(reranker.rerank(query, &docs)).expect("rerank");
        let dur = t4.elapsed();
        println!(
            "[重排] {}条候选推理: {:.1}ms, 单条均值 {:.1}ms",
            k,
            dur.as_secs_f64() * 1000.0,
            dur.as_secs_f64() * 1000.0 / k as f64
        );
    }

    // 峰值内存（Linux /proc/self/status）
    if let Ok(s) = std::fs::read_to_string("/proc/self/status") {
        for line in s.lines() {
            if line.starts_with("VmPeak:") || line.starts_with("VmRSS:") {
                println!("[内存] {line}");
            }
        }
    }
}