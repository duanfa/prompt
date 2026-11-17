import fs from 'node:fs/promises';
import path from 'node:path';
import { FileBlob, SpreadsheetFile, Workbook } from '@oai/artifact-tool';

const C = 'dws_lgw_risk_customer_warn_sum';
const W = 'dws_lgw_risk_worker_warn_detail';
const E = 'dwd_lgw_risk_worker_warn_month_evidence';
const COLOR = { navy: '#223B57', text: '#202C39', muted: '#64748B', section: '#EEF3F8', stripe: '#F7F9FB', amber: '#FFF2CC', red: '#FCE4D6' };
const MONEY = '#,##0.00';
const RATE = '0.00%';
const INT = '#,##0';
const DATETIME = 'yyyy-mm-dd hh:mm:ss';
const col = n => { let s=''; for (n++; n>0; n=Math.floor((n-1)/26)) s=String.fromCharCode(65+(n-1)%26)+s; return s; };
const literal = value => typeof value === 'string' && /^[=+@-]/.test(value) ? `'${value}` : value;
const show = value => value == null || value === '' ? '未提供' : literal(value);
const dateValue = value => value ? new Date(value.replace(' ','T')+'Z') : '未提供';
function numeric(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) throw new Error(`Excel 数字无效：${value}`);
  // Excel keeps 15 significant digits. Reject amounts that would silently lose cents.
  if (typeof value === 'string' && value.replace(/^[-+]?0*|\.|0+$/g, '').length > 15) {
    throw new Error(`数值超过 Excel 的15位有效数字精度：${value}`);
  }
  return n;
}
function write(sheet, cell, value) { sheet.getRange(cell).values = [[literal(value)]]; }
function formula(sheet, cell, value) { sheet.getRange(cell).formulas = [[value]]; }
function mergedText(sheet, address, value, height=30) {
  const range=sheet.getRange(address); range.merge(); range.values=[[literal(value)]];
  range.format.wrapText=true; range.format.rowHeight=height;
}
function section(sheet, address, value) {
  mergedText(sheet,address,value,28);
  sheet.getRange(address).format.fill=COLOR.section;
  sheet.getRange(address).format.font={name:'Microsoft YaHei',size:11,bold:true,color:COLOR.navy};
}
function header(sheet,address) {
  const range=sheet.getRange(address);
  range.format={fill:COLOR.navy,font:{name:'Microsoft YaHei',size:11,bold:true,color:'#FFFFFF'},
    horizontalAlignment:'center',verticalAlignment:'center',wrapText:true,rowHeight:44};
}
function base(sheet,address) {
  sheet.showGridLines=false;
  sheet.getRange(address).format={fill:'#FFFFFF',font:{name:'Microsoft YaHei',size:11,color:COLOR.text},
    verticalAlignment:'center',rowHeight:30,wrapText:false};
}
function table(sheet, row, headers, rows, name, numberCols={}, editable=[]) {
  const lastCol=col(headers.length-1), bottom=row+Math.max(rows.length,1);
  sheet.getRange(`A${row}:${lastCol}${bottom}`).format.borders={preset:'none'};
  sheet.getRange(`A${row}`).write([headers,...(rows.length ? rows : [Array(headers.length).fill(null)])]);
  const t=sheet.tables.add(`A${row}:${lastCol}${bottom}`,true,name);
  t.style='TableStyleMedium2'; t.showFilterButton=true;
  header(sheet,`A${row}:${lastCol}${row}`);
  sheet.getRange(`A${row+1}:${lastCol}${bottom}`).format.rowHeight=32;
  for(const [column,fmt] of Object.entries(numberCols)) {
    sheet.getRange(`${column}${row+1}:${column}${bottom}`).setNumberFormat(fmt);
    sheet.getRange(`${column}${row+1}:${column}${bottom}`).format.horizontalAlignment='right';
  }
  for(const column of editable) sheet.getRange(`${column}${row+1}:${column}${bottom}`).format.fill=COLOR.amber;
  return bottom;
}
function highlight(sheet,address,expression) {
  sheet.getRange(address).conditionalFormats.addCustom(expression,{fill:COLOR.red,font:{color:'#9C0006',bold:true}});
}

async function initTemplate(layoutPath, output) {
  const layout=JSON.parse(await fs.readFile(layoutPath,'utf8'));
  const wb=Workbook.create();
  for(const spec of layout) {
    const sheet=wb.worksheets.add(spec.name); sheet.showGridLines=false;
    for(const [letter,width] of spec.widths) sheet.getRange(`${letter}:${letter}`).format.columnWidth=width;
    for(const [row,height] of spec.heights) sheet.getRange(`A${row}:${col(spec.cols-1)}${row}`).format.rowHeight=height;
    for(const cell of spec.cells) {
      const range=sheet.getRange(cell.address);
      range.format=cell.format;
      if(cell.value !== null) range.values=[[literal(cell.value)]];
    }
    for(const merge of spec.merges) sheet.mergeCells(merge);
  }
  wb.recalculate();
  await (await SpreadsheetFile.exportXlsx(wb)).save(output);
}

async function fill(request) {
  const {tables,issues,mock,template,output,previewDir}=request;
  const customers=tables[C], workers=[...tables[W]].sort((a,b)=>(a.main_rule!=='R02')-(b.main_rule!=='R02')||a.customer_id.localeCompare(b.customer_id)||a.currency.localeCompare(b.currency)||a.warn_id.localeCompare(b.warn_id));
  const evidence=[...tables[E]].sort((a,b)=>a.warn_id.localeCompare(b.warn_id)||a.obs_month.localeCompare(b.obs_month));
  const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(template));
  const main=wb.worksheets.getItem('风控报告样式');
  const months=wb.worksheets.add('月度证据');
  const handling=wb.worksheets.add('核查与参数');
  const customerBottom=10+Math.max(customers.length,1), workerTitle=customerBottom+3, workerHeader=workerTitle+1;
  const workerFirst=workerHeader+1, workerBottom=workerHeader+Math.max(workers.length,1), finalRow=workerBottom+8;
  main.getRange('A10:P52').unmerge();
  main.getRange(`A10:P${Math.max(52,finalRow)}`).clear({applyTo:'contents'});
  // Reuse the template's two table row styles, placing the lower table before expanding customers.
  const copyWorkerHeader=()=>main.getRange(`A${workerHeader}:P${workerHeader}`).copyFrom(main.getRange('A17:P17'),'all');
  if(workerHeader<17) copyWorkerHeader();
  for(let r=workerBottom;r>=workerFirst;r--) main.getRange(`A${r}:P${r}`).copyFrom(main.getRange('A18:P18'),'all');
  if(workerHeader>=17) copyWorkerHeader();
  for(let r=customerBottom;r>=11;r--) main.getRange(`A${r}:P${r}`).copyFrom(main.getRange('A11:P11'),'all');
  base(main,`A10:P${finalRow}`);
  main.getRange(`A${finalRow+1}:P${Math.max(52,finalRow+1)}`).clear({applyTo:'all'});
  const widths=[21,24,19,21,13,12,12,18,16,17,21,15,17,18,18,32];
  widths.forEach((width,i)=>main.getRange(`${col(i)}:${col(i)}`).format.columnWidth=width);
  write(main,'A2','灵工固定用工特征风控报告 多客户版');
  main.getRange('A2:P2').format.horizontalAlignment='left';
  write(main,'A3',mock ? '模拟演示数据。每条人员预警对应客户＋灵工＋币种，同一灵工在不同客户下分别识别。' : '每条人员预警对应客户＋灵工＋币种；本报告仅覆盖本次接口返回范围。');
  main.getRange('A3:P3').format.rowHeight=32;
  write(main,'C4',customers.length ? new Date(`${customers[0].ds.slice(0,4)}-${customers[0].ds.slice(4,6)}-${customers[0].ds.slice(6,8)}T00:00:00Z`) : '未提供');
  main.getRange('C4').setNumberFormat('yyyy-mm-dd');
  const periods=[...new Set(customers.map(r=>`${r.obs_start_month}至${r.obs_end_month}`))];
  write(main,'F4',`${periods.join('；')||'未提供'}；R02见人员参数（6个月）`);
  const currencies=[...new Set(customers.map(r=>r.currency))].sort();
  write(main,'M4',`${customers[0]?.rule_version||'未提供'} / ${currencies.join('、')||'未提供'}`);
  write(main,'A5',issues.length ? `数据存在${issues.length}项核对异常，相关结论待核对，详见“核查与参数”。` : customers.length ? '本次返回范围的三表一致性校验通过。预警为疑似线索，不自动阻断发放。' : '当前响应无已评估客户，不能据此推断全部客户无风险。');
  main.getRange('A5:P5').format.rowHeight=30;
  if(issues.length) main.getRange('A5:P5').format.fill=COLOR.red;
  write(main,'A6','已评估客户'); write(main,'D6','客户聚集预警'); write(main,'G6','客户－灵工预警数'); write(main,'J6','重点人员预警数');
  write(main,'M6',currencies.length===1 ? `涉及金额（近3月，${currencies[0]}元）` : '涉及金额（按币种分别统计）');
  write(main,'A7',new Set(customers.map(r=>r.customer_id)).size);
  formula(main,'D7',`=COUNTIF(I11:I${customerBottom},"R03命中")`);
  formula(main,'G7',`=SUM(E11:E${customerBottom})`);
  formula(main,'J7',`=SUM(G11:G${customerBottom})`);
  if(currencies.length===1) { formula(main,'M7',`=SUM(H11:H${customerBottom})`); main.getRange('M7:P7').setNumberFormat(MONEY); }
  else write(main,'M7',currencies.length ? '见下方分币种金额' : '无记录');
  write(main,'A9','客户风险汇总 每行一个客户＋币种，可筛选客户及预警结果');
  const customerRows=customers.map(r=>[
    r.customer_id,r.customer_name,r.currency,r.total_worker_cnt,r.regular_worker_cnt,
    r.total_worker_cnt ? numeric(r.hit_worker_ratio) : '无法评估',r.r02_worker_cnt,numeric(r.involved_amount),
    r.total_worker_cnt ? (r.is_customer_warn==='1'?'R03命中':'未命中') : '无法评估',r.priority,
    ...['待核查','核查中','已关闭'].map(status=>workers.filter(w=>w.customer_id===r.customer_id&&w.currency===r.currency&&w.warn_status===status).length),
    r.warn_status,show(r.handler),show(r.check_conclusion)
  ].map(literal));
  table(main,10,['客户ID','客户名称','币种','发放人数U','规律人数H','命中占比','R02人数','涉及金额(元)','客户预警','核查优先级','人员待核查','人员核查中','人员已关闭','客户核查状态','负责人','核查结论'],customerRows,'CustomerRiskSummary',
    {D:INT,E:INT,F:RATE,G:INT,H:MONEY,K:INT,L:INT,M:INT});
  mergedText(main,`A${customerBottom+1}:P${customerBottom+1}`,'H含R02且不重复；U取客户全量人数。客户未命中R03时，其人员预警仍需核查。',28);
  section(main,`A${workerTitle}:P${workerTitle}`,'命中人员明细 每行一条客户－灵工－币种预警，可按规则及状态筛选');
  const workerRows=workers.map(r=>[
    r.warn_id,r.customer_id,r.customer_name,r.worker_id,r.worker_name_masked,r.currency,r.main_rule,r.priority,r.cover_month_cnt,
    numeric(r.volatility),numeric(r.total_amount_3m),r.anchor_day,numeric(r.min_window_ratio),r.warn_status,show(r.handler),show(r.check_conclusion)
  ].map(literal));
  table(main,workerHeader,['预警ID','客户ID','客户名称','灵工ID','脱敏姓名','币种','主要规则','优先级','覆盖月数','金额波动率','近3月金额(元)','固定发放日','最低窗口占比','核查状态','负责人','核查结论'],workerRows,'WorkerRiskAlerts',
    {I:INT,J:RATE,K:MONEY,L:INT,M:RATE});
  if(customers.length) highlight(main,`I11:I${customerBottom}`,'$I11="R03命中"');
  if(workers.length) highlight(main,`H${workerFirst}:H${workerBottom}`,`$H${workerFirst}="重点"`);
  mergedText(main,`A${workerBottom+2}:P${workerBottom+2}`,'人数按客户－灵工－币种关系计数，不能视为平台去重人数。月度证据完整列于“月度证据”，核查依据、关闭时间和观察期参数见“核查与参数”。',36);
  section(main,`A${workerBottom+3}:P${workerBottom+3}`,'金额统计 按币种列示，客户全量金额包含预警人员部分，二者不可相加');
  header(main,`A${workerBottom+4}:F${workerBottom+4}`);
  mergedText(main,`A${workerBottom+4}:B${workerBottom+4}`,'币种',32);
  mergedText(main,`C${workerBottom+4}:D${workerBottom+4}`,'客户全部有效金额（元）',32);
  mergedText(main,`E${workerBottom+4}:F${workerBottom+4}`,'其中预警人员金额（元）',32);
  for(let i=0;i<currencies.length;i++) {
    const r=workerBottom+5+i;
    base(main,`A${r}:P${r}`);
    mergedText(main,`A${r}:B${r}`,currencies[i],30);
    main.getRange(`C${r}:D${r}`).merge(); main.getRange(`E${r}:F${r}`).merge();
    formula(main,`C${r}`,`=SUMIF(C11:C${customerBottom},A${r},H11:H${customerBottom})`);
    formula(main,`E${r}`,`=SUMIF(F${workerFirst}:F${workerBottom},A${r},K${workerFirst}:K${workerBottom})`);
    main.getRange(`C${r}:F${r}`).setNumberFormat(MONEY);
  }
  const noteRow=Math.max(workerBottom+7,workerBottom+6+currencies.length);
  mergedText(main,`A${noteRow}:P${noteRow}`,'报告判定：规则命中为疑似固定用工特征，不能据此确认历史员工身份或劳务转灵工事实。请在“核查与参数”的黄色区域填写核查信息，报告状态会同步更新。',36);
  main.freezePanes.freezeRows(10); main.tabColor=COLOR.navy;

  // All 17 SQL evidence fields are retained, with business labels and typed numeric cells.
  const evidenceFields=['warn_id','customer_id','worker_id','currency','obs_month','obs_month_seq','has_pay_flag','month_amount','pay_cnt','anchor_day','window_start','window_end','window_amount','window_ratio','rule_version','ds','etl_time'];
  base(months,`A1:Q${Math.max(5,evidence.length+4)}`);
  mergedText(months,'A2:Q2','预警月度证据 全部预警、全部观察月份',32);
  months.getRange('A2:Q2').format.font={name:'Microsoft YaHei',size:16,bold:true,color:COLOR.navy};
  mergedText(months,'A3:Q3',mock?'模拟演示数据；按预警ID关联，跨客户分别识别。':'按预警ID关联；缺月表示证据不足，不能用零补齐。',28);
  table(months,4,['预警ID','客户ID','灵工ID','币种','月份','月序','有效发放标志','月金额(元)','发放笔数','当月锚定日','窗口起始日','窗口截止日','窗口金额(元)','窗口占比','规则版本','评估批次ds','更新时间'],evidence.map(r=>evidenceFields.map(k=>['month_amount','window_amount','window_ratio'].includes(k)?numeric(r[k]):k==='etl_time'?dateValue(r[k]):literal(r[k]))),'MonthlyEvidence',
    {F:INT,H:MONEY,I:INT,J:INT,K:INT,L:INT,M:MONEY,N:RATE,Q:DATETIME});
  months.getRange(`G5:G${Math.max(5,evidence.length+4)}`).format.horizontalAlignment='center';
  [14,21,21,11,14,9,15,19,11,13,13,13,19,14,13,16,26].forEach((width,i)=>months.getRange(`${col(i)}:${col(i)}`).format.columnWidth=width);
  months.freezePanes.freezeRows(4); months.freezePanes.freezeColumns(3);

  const handlingRows=[...customers.map(r=>['客户',r.customer_id,r.customer_name,r.currency,null,null,null,null,r.obs_start_month,r.obs_end_month,null,null,null,r.worker_cnt_threshold,numeric(r.ratio_threshold),r.warn_status,show(r.handler),show(r.check_conclusion),show(r.check_basis),dateValue(r.close_time),null,null,null,r.rule_version,r.ds,dateValue(r.etl_time)]),
    ...workers.map(r=>['人员',r.customer_id,r.customer_name,r.currency,r.warn_id,r.worker_id,r.obs_start_month,r.obs_end_month,null,null,numeric(r.month_amount_min),numeric(r.month_amount_max),numeric(r.amount_tolerance),null,null,r.warn_status,show(r.handler),show(r.check_conclusion),show(r.check_basis),dateValue(r.close_time),dateValue(r.first_hit_time),dateValue(r.last_hit_time),r.is_upgraded,r.rule_version,r.ds,dateValue(r.etl_time)])].map(r=>r.map(literal));
  base(handling,`A1:AA${handlingRows.length+issues.length+16}`);
  mergedText(handling,'A2:Z2','核查处理与参数快照',32);
  handling.getRange('A2:Z2').format.font={name:'Microsoft YaHei',size:16,bold:true,color:COLOR.navy};
  mergedText(handling,'A3:Z3','黄色为人工核查字段；未提供的信息保持未提供，已关闭必须有负责人、结论、依据及关闭时间。',28);
  const handleBottom=table(handling,4,['对象类型','客户ID','客户名称','币种','预警ID','灵工ID','人员观察起始月','人员观察截止月','客户观察起始月','客户观察截止月','最低月金额(元)','最高月金额(元)','金额容差','R03人数阈值','R03占比阈值','核查状态','负责人','核查结论','核查依据','关闭时间','首次命中时间','最近命中时间','是否升级标志','规则版本','评估批次ds','更新时间','记录关联键'],handlingRows.map(r=>[...r,null]),'HandlingParameters',
    {K:MONEY,L:MONEY,M:RATE,N:INT,O:RATE,T:DATETIME,U:DATETIME,V:DATETIME,Z:DATETIME},['P','Q','R','S','T']);
  // Length-prefixed customer IDs avoid separator collisions. Keys follow the record when sorted.
  for(let row=5;row<=handleBottom;row++) {
    formula(handling,`AA${row}`,`=IF(A${row}="客户","客户:"&LEN(B${row})&":"&B${row}&":"&D${row},"人员:"&E${row})`);
  }
  handling.getRange('AA:AA').format.columnWidth=34;
  const linked=(dest,column,key)=>{
    const lookup=`INDEX('核查与参数'!$${column}$5:$${column}$${handleBottom},MATCH(${key},'核查与参数'!$AA$5:$AA$${handleBottom},0))`;
    formula(main,dest,`=IFERROR(IF(${lookup}="","未提供",${lookup}),"未提供")`);
  };
  customers.forEach((r,i)=>{
    const out=11+i, key=`"客户:"&LEN(A${out})&":"&A${out}&":"&C${out}`;
    linked(`N${out}`,'P',key); linked(`O${out}`,'Q',key); linked(`P${out}`,'R',key);
    ['待核查','核查中','已关闭'].forEach((status,j)=>formula(main,`${col(10+j)}${out}`,
      `=COUNTIFS($B$${workerFirst}:$B$${workerBottom},$A${out},$F$${workerFirst}:$F$${workerBottom},$C${out},$N$${workerFirst}:$N$${workerBottom},"${status}")`));
  });
  workers.forEach((r,i)=>{
    const out=workerFirst+i, key=`"人员:"&A${out}`;
    linked(`N${out}`,'P',key); linked(`O${out}`,'Q',key); linked(`P${out}`,'R',key);
  });
  // Extra worker parameter table keeps window_days from the original SQL as an explicit snapshot.
  const paramHeader=handleBottom+3;
  section(handling,`A${paramHeader-1}:Z${paramHeader-1}`,'人员规则参数补充');
  table(handling,paramHeader,['预警ID','日期窗口(±日)','覆盖月数','固定发放日','最低窗口占比','近3月金额(元)','金额波动率'],workers.map(r=>[r.warn_id,r.window_days,r.cover_month_cnt,r.anchor_day,numeric(r.min_window_ratio),numeric(r.total_amount_3m),numeric(r.volatility)]),'WorkerParameterDetails',
    {B:INT,C:INT,D:INT,E:RATE,F:MONEY,G:RATE});
  const issueTitle=paramHeader+Math.max(workers.length,1)+3;
  section(handling,`A${issueTitle}:Z${issueTitle}`,'数据核对与未提供资料');
  const issueLines=issues.length ? [`存在${issues.length}项数据异常。相关统计与预警结论待核对；保留上游值，不以缺失替代零或未命中。`,...issues] : ['三表关联、完整月份、人数、金额及参数一致性检查通过；不代表上游源数据已完整采集。'];
  issueLines.push('当前响应无已评估客户时，仅代表所选范围无返回记录，不能推断全部客户无风险。',
    '原流水、员工名单、社保、考勤、合同、任务单及后续措施未由三张结果表提供，保持未提供；锚点枚举最优性需另调源流水核实。',
    '先核查R03客户与R02重点人员，再处理普通人员预警。持续命中仅更新，普通升级重点追加提醒；报告生成不会自动发送提醒或关闭工单。');
  issueLines.forEach((line,i)=>mergedText(handling,`A${issueTitle+1+i}:Z${issueTitle+1+i}`,line,32));
  if(issues.length) handling.getRange(`A${issueTitle+1}:Z${issueTitle+1+issues.length}`).format.fill=COLOR.red;
  for(let i=0;i<26;i++) handling.getRange(`${col(i)}:${col(i)}`).format.columnWidth=[1,2,5].includes(i)?24:[18].includes(i)?48:[19,20,21,25].includes(i)?25:18;
  handling.getRange(`S5:S${handleBottom}`).format.wrapText=true;
  if(handlingRows.length) {
    handling.getRange(`P5:P${handleBottom}`).dataValidation={rule:{type:'list',values:['待核查','核查中','已关闭']}};
    handling.getRange(`R5:R${handleBottom}`).dataValidation={rule:{type:'list',values:['存在风险','合理业务场景','证据不足']}};
    highlight(handling,`P5:T${handleBottom}`,'AND($P5="已关闭",OR($Q5="",$Q5="未提供",$R5="",$R5="未提供",$S5="",$S5="未提供",$T5="",$T5="未提供"))');
  }
  handling.freezePanes.freezeRows(4); handling.freezePanes.freezeColumns(2);
  wb.recalculate();
  const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:50},maxChars:3000});
  if(/"kind":"match"/.test(errors.ndjson)) throw new Error(`工作簿公式错误：${errors.ndjson}`);
  const checks={main:(await wb.inspect({kind:'table',range:'风控报告样式!A6:P7',tableMaxRows:2,tableMaxCols:16,maxChars:3000})).ndjson,
    formulaErrors:errors.ndjson,rows:{customers:customers.length,workers:workers.length,evidence:evidence.length},dataIssues:issues};
  if(previewDir) {
    await fs.mkdir(previewDir,{recursive:true});
    for(const [sheetName,range,name] of [['风控报告样式',`A1:P${Math.min(workerHeader+3,28)}`,'report'],['月度证据','A1:Q10','evidence'],['核查与参数','A1:Z10','handling'],['风控规则','A1:E14','rules']]) {
      const png=await wb.render({sheetName,range,scale:1.3,format:'png'});
      await fs.writeFile(path.join(previewDir,`${name}.png`),new Uint8Array(await png.arrayBuffer()));
    }
    await fs.writeFile(path.join(previewDir,'checks.json'),JSON.stringify(checks,null,2));
  }
  await fs.mkdir(path.dirname(output),{recursive:true});
  const pending=output.replace(/\.xlsx$/i,`.pending-${process.pid}.xlsx`);
  try { await (await SpreadsheetFile.exportXlsx(wb)).save(pending); await fs.rename(pending,output); }
  finally { await fs.rm(pending,{force:true}); await fs.rm(`${pending}.inspect.ndjson`,{force:true}); }
  console.log(JSON.stringify(checks));
}

try {
  if(process.argv[2]==='--init-template') await initTemplate(process.argv[3],process.argv[4]);
  else await fill(JSON.parse(await fs.readFile(process.argv[2],'utf8')));
} catch(error) { console.error(error.stack||String(error)); process.exitCode=2; }
