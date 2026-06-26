(function() {
  var style = getComputedStyle(document.documentElement);
  var accent = style.getPropertyValue('--accent').trim();
  var accent2 = style.getPropertyValue('--accent2').trim();
  var success = style.getPropertyValue('--success').trim();
  var warning = style.getPropertyValue('--warning').trim();
  var danger = style.getPropertyValue('--danger').trim();
  var ink = style.getPropertyValue('--ink').trim();
  var muted = style.getPropertyValue('--muted').trim();
  var rule = style.getPropertyValue('--rule').trim();
  var bg2 = style.getPropertyValue('--bg2').trim();

  var chart1 = echarts.init(document.getElementById('chart-issues'), null, { renderer: 'svg' });
  chart1.setOption({
    animation: false,
    tooltip: { trigger: 'item', appendToBody: true },
    legend: {
      orient: 'vertical',
      right: '5%',
      top: 'center',
      textStyle: { color: ink }
    },
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      center: ['40%', '50%'],
      avoidLabelOverlap: true,
      itemStyle: { borderRadius: 6, borderColor: bg2, borderWidth: 2 },
      label: { show: true, color: ink, formatter: '{b}: {c}' },
      labelLine: { lineStyle: { color: muted } },
      data: [
        { value: 2, name: '严重问题', itemStyle: { color: danger } },
        { value: 8, name: '警告项', itemStyle: { color: warning } },
        { value: 4, name: '建议优化', itemStyle: { color: accent } }
      ]
    }]
  });
  window.addEventListener('resize', function() { chart1.resize(); });
})();
