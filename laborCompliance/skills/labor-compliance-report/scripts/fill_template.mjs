import fs from 'node:fs/promises';
import path from 'node:path';
import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';

const C='dws_lgw_risk_customer_warn_sum', W='dws_lgw_risk_worker_warn_detail', E='dwd_lgw_risk_worker_warn_month_evidence';
const SHEETS=['灵工固定用工特征风控报告','客户风险汇总','命中人员明细','月度证据'];
const COLOR={navy:'#223B57',text:'#202C39',section:'#EEF3F8',amber:'#FFF2CC',red:'#FCE4D6'};
const MONEY='#,##0.00', RATE='0.0%', INT='#,##0', DATETIME='yyyy-mm-dd hh:mm:ss';
const col=n=>{let s='';for(n++;n>0;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s;};
const literal=value=>typeof value==='string'&&/^[=+@-]/.test(value)?`'${value}`:value;
const show=value=>value==null||value===''?'未提供':literal(value);
const dateValue=value=>value?new Date(value.replace(' ','T')+'Z'):'未提供';
function numeric(value){
  const n=Number(value);
  if(!Number.isFinite(n))throw new Error(`Excel 数字无效：${value}`);
  if(typeof value==='string'&&value.replace(/^[-+]?0*|\.|0+$/g,'').length>15)throw new Error(`数值超过 Excel 的15位有效数字精度：${value}`);
  return n;
}
function write(s,cell,v){s.getRange(cell).values=[[literal(v)]];}
function formula(s,cell,v){s.getRange(cell).formulas=[[v]];}
function text(s,address,v,height=30){const r=s.getRange(address);r.merge();write(s,address.split(':')[0],v);r.format.wrapText=true;r.format.rowHeight=height;}
function section(s,address,v){text(s,address,v);s.getRange(address).format.fill=COLOR.section;s.getRange(address).format.font={name:'Microsoft YaHei',size:11,bold:true,color:COLOR.navy};}
function widths(s,values){values.forEach((w,i)=>s.getRange(`${col(i)}:${col(i)}`).format.columnWidth=w);}
function table(s,row,headers,rows,name,formats={},editable=[]){
  const last=col(headers.length-1),bottom=row+Math.max(rows.length,1);
  s.getRange(`A${row}:${last}${bottom}`).values=[headers,...(rows.length?rows:[Array(headers.length).fill(null)])];
  const t=s.tables.add(`A${row}:${last}${bottom}`,true,name);t.style='TableStyleMedium2';t.showFilterButton=true;
  s.getRange(`A${row}:${last}${row}`).format={fill:COLOR.navy,font:{name:'Microsoft YaHei',size:11,bold:true,color:'#FFFFFF'},horizontalAlignment:'center',verticalAlignment:'center',wrapText:true,rowHeight:48};
  s.getRange(`A${row+1}:${last}${bottom}`).format.rowHeight=34;
  for(const [c,fmt]of Object.entries(formats)){const r=s.getRange(`${c}${row+1}:${c}${bottom}`);r.setNumberFormat(fmt);r.format.horizontalAlignment='right';}
  for(const c of editable)s.getRange(`${c}${row+1}:${c}${bottom}`).format.fill=COLOR.amber;
  return bottom;
}
function highlight(s,address,expression){s.getRange(address).conditionalFormats.addCustom(expression,{fill:COLOR.red,font:{color:'#9C0006',bold:true}});}
function handlingValidation(s,first,last,status,conclusion){
  s.getRange(`${status}${first}:${status}${last}`).dataValidation={rule:{type:'list',values:['待核查','核查中','已关闭']}};
  s.getRange(`${conclusion}${first}:${conclusion}${last}`).dataValidation={rule:{type:'list',values:['未提供','存在风险','合理业务场景','证据不足']}};
}

async function fill(request){
  const {tables,issues,mock,template,output,previewDir,checksFile}=request;
  const customers=tables[C];
  const workers=[...tables[W]].sort((a,b)=>(a.main_rule!=='R02')-(b.main_rule!=='R02')||a.customer_id.localeCompare(b.customer_id)||a.currency.localeCompare(b.currency)||a.warn_id.localeCompare(b.warn_id));
  const evidence=[...tables[E]].sort((a,b)=>a.warn_id.localeCompare(b.warn_id)||a.obs_month.localeCompare(b.obs_month));
  const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(template));
  const sheetInfo=await wb.inspect({kind:'sheet',include:'id,name',maxChars:5000});
  const actual=sheetInfo.ndjson.trim().split('\n').filter(Boolean).map(line=>JSON.parse(line).name);
  if(JSON.stringify(actual)!==JSON.stringify(SHEETS))throw new Error(`Excel 模板工作表不匹配；需要依次为：${SHEETS.join('、')}`);
  const [main,cs,ws,months]=SHEETS.map(name=>wb.worksheets.getItem(name));
  // Reuse styles, but never retain the user's sample records or sample formulas.
  for(const s of [cs,ws,months]){for(const t of [...s.tables.items])t.delete();s.getUsedRange().conditionalFormats.clear();s.getUsedRange().dataValidation=null;}
  cs.getRange('A6:P6').unmerge();cs.getRange('A3:P7').clear({applyTo:'contents'});
  ws.getRange('A26:P26').unmerge();ws.getRange('A3:P26').clear({applyTo:'contents'});
  months.getRange('A1:P9').unmerge();months.getRange('A1:P9').clear({applyTo:'contents'});
  const cb=2+Math.max(customers.length,1),wbott=2+Math.max(workers.length,1);
  for(let row=cb;row>=4;row--)cs.getRange(`A${row}:M${row}`).copyFrom(cs.getRange('A3:M3'),'all');
  for(let row=wbott;row>=4;row--)ws.getRange(`A${row}:P${row}`).copyFrom(ws.getRange('A3:P3'),'all');
  if(cb<5)cs.getRange(`A${cb+1}:M5`).clear({applyTo:'all'});
  if(wbott<25)ws.getRange(`A${wbott+1}:P25`).clear({applyTo:'all'});
  // The supplied template has no column widths. Fit values while keeping its column order.
  widths(main,Array(16).fill(11));
  widths(cs,[21,24,13,13,13,12,20,16,15,12,14,18,26,12,12,12]);
  widths(ws,[16,21,24,21,13,12,12,12,14,22,15,15,14,18,24,38,12,25,15,15,20,20,14,14,25,25,14,15,16,25]);
  widths(months,Array(16).fill(12));months.getRange('Q:Q').format.columnWidth=25;
  for(const s of [main,cs,ws,months])s.showGridLines=false;
  const currencies=[...new Set(customers.map(r=>r.currency))].sort();
  write(cs,'A1','客户风险汇总 每行一个客户＋币种，可筛选客户及预警结果');
  table(cs,2,['客户ID','客户名称','发放人数U','规律人数H','命中占比','R02人数','涉及金额(元)','客户预警','核查优先级','币种','核查状态','负责人','核查结论'],
    customers.map(r=>[r.customer_id,r.customer_name,r.total_worker_cnt,r.regular_worker_cnt,r.total_worker_cnt?numeric(r.hit_worker_ratio):'无法评估',r.r02_worker_cnt,numeric(r.involved_amount),r.total_worker_cnt?(r.is_customer_warn==='1'?'R03命中':'未命中'):'无法评估',r.priority,r.currency,r.warn_status,show(r.handler),show(r.check_conclusion)].map(literal)),
    'CustomerRiskSummary',{C:INT,D:INT,E:RATE,F:INT,G:MONEY},['K','L','M']);
  cs.getRange(`C3:C${cb}`).format.fill='#FFFFFF';
  text(cs,'N3:P5','U取客户全部有效发放去重人数，H含R02且不重复。客户未命中R03时，其人员预警仍需核查。金额按币种列示。',34);
  const parameterTitle=Math.max(cb+4,9),ph=parameterTitle+1;
  text(cs,`A${Math.max(cb+2,7)}:P${Math.max(cb+2,7)}`,'人数按客户－灵工－币种关系计数，不是平台去重人数。黄色为人工核查输入；依据、关闭时间及人员状态统计见下方参数表。',32);
  section(cs,`A${parameterTitle}:P${parameterTitle}`,'客户核查资料、规则参数与人员状态');
  const pb=table(cs,ph,['客户ID','币种','核查依据','关闭时间','观察起始月','观察截止月','R03人数阈值','R03占比阈值','规则版本','评估批次ds','更新时间','人员待核查','人员核查中','人员已关闭','预警人员近3月金额(元)'],
    customers.map(r=>[r.customer_id,r.currency,show(r.check_basis),dateValue(r.close_time),r.obs_start_month,r.obs_end_month,r.worker_cnt_threshold,numeric(r.ratio_threshold),r.rule_version,r.ds,dateValue(r.etl_time),null,null,null,null].map(literal)),
    'CustomerParameters',{D:DATETIME,G:INT,H:RATE,K:DATETIME,L:INT,M:INT,N:INT,O:MONEY},['C','D']);
  cs.getRange(`A${ph}:O${pb}`).format.wrapText=true;cs.getRange(`A${ph}:O${pb}`).format.rowHeight=64;
  cs.getRange(`D${ph+1}:D${pb}`).setNumberFormat('yyyy-mm-dd"\n"hh:mm:ss');cs.getRange(`K${ph+1}:K${pb}`).setNumberFormat('yyyy-mm-dd"\n"hh:mm:ss');
  if(customers.length){
    highlight(cs,`H3:H${cb}`,'$H3="R03命中"');handlingValidation(cs,3,cb,'K','M');
    highlight(cs,`K3:M${cb}`,`AND($K3="已关闭",OR($L3="",$L3="未提供",$M3="",$M3="未提供",COUNTIFS($A$${ph+1}:$A$${pb},$A3,$B$${ph+1}:$B$${pb},$J3,$C$${ph+1}:$C$${pb},"<>",$C$${ph+1}:$C$${pb},"<>未提供",$D$${ph+1}:$D$${pb},"<>",$D$${ph+1}:$D$${pb},"<>未提供")=0))`);
  }
  write(ws,'A1','命中人员明细 每行一条客户－灵工－币种预警，可按客户、规则、核查状态筛选');
  table(ws,2,['预警ID','客户ID','客户名称','灵工ID','脱敏姓名','主要规则','优先级','覆盖月数','金额波动率','近3月累计应发金额(元)','固定发放日（系统识别）','最低窗口占比','核查状态','负责人','核查结论','核查依据','币种','关闭时间','观察起始月','观察截止月','最低月金额(元)','最高月金额(元)','金额容差','日期窗口(±日)','首次命中时间','最近命中时间','是否升级标志','规则版本','评估批次ds','更新时间'],
    workers.map(r=>[r.warn_id,r.customer_id,r.customer_name,r.worker_id,r.worker_name_masked,r.main_rule,r.priority,r.cover_month_cnt,numeric(r.volatility),numeric(r.total_amount_3m),r.anchor_day,numeric(r.min_window_ratio),r.warn_status,show(r.handler),show(r.check_conclusion),show(r.check_basis),r.currency,dateValue(r.close_time),r.obs_start_month,r.obs_end_month,numeric(r.month_amount_min),numeric(r.month_amount_max),numeric(r.amount_tolerance),r.window_days,dateValue(r.first_hit_time),dateValue(r.last_hit_time),r.is_upgraded,r.rule_version,r.ds,dateValue(r.etl_time)].map(literal)),
    'WorkerRiskAlerts',{H:INT,I:RATE,J:MONEY,K:'0"日"',L:RATE,R:DATETIME,U:MONEY,V:MONEY,W:RATE,X:INT,Y:DATETIME,Z:DATETIME,AD:DATETIME},['M','N','O','P','R']);
  ws.getRange(`P3:P${wbott}`).format.wrapText=true;
  if(workers.length){handlingValidation(ws,3,wbott,'M','O');highlight(ws,`G3:G${wbott}`,'$G3="重点"');
    highlight(ws,`M3:R${wbott}`,'AND($M3="已关闭",OR($N3="",$N3="未提供",$O3="",$O3="未提供",$P3="",$P3="未提供",$R3="",$R3="未提供"))');}
  text(ws,`A${wbott+2}:P${wbott+2}`,'黄色为人工核查字段；关闭须具备负责人、结论、核查依据和关闭时间。币种、关闭时间和完整规则参数在Q列起。汇总反映全部记录，筛选仅改变可见行。',34);
  customers.forEach((r,i)=>{const row=ph+1+i;
    ['待核查','核查中','已关闭'].forEach((status,j)=>formula(cs,`${col(11+j)}${row}`,`=COUNTIFS('命中人员明细'!$B$3:$B$${wbott},$A${row},'命中人员明细'!$Q$3:$Q$${wbott},$B${row},'命中人员明细'!$M$3:$M$${wbott},"${status}")`));
    formula(cs,`O${row}`,`=SUMIFS('命中人员明细'!$J$3:$J$${wbott},'命中人员明细'!$B$3:$B$${wbott},$A${row},'命中人员明细'!$Q$3:$Q$${wbott},$B${row})`);
  });
  cs.freezePanes.freezeRows(2);cs.freezePanes.freezeColumns(2);ws.freezePanes.freezeRows(2);ws.freezePanes.freezeColumns(2);

  // Repeat the supplied six-month card for every alert. The full SQL evidence follows below.
  const byWarn=new Map();for(const e of evidence){if(!byWarn.has(e.warn_id))byWarn.set(e.warn_id,[]);byWarn.get(e.warn_id).push(e);}
  workers.forEach((r,i)=>{
    const first=1+i*6,entries=byWarn.get(r.warn_id)||[];
    section(months,`A${first}:P${first}`,`${r.warn_id} / ${r.customer_name} / ${r.worker_id} / ${r.currency} / ${r.main_rule}（${r.obs_start_month}至${r.obs_end_month}）`);
    for(let m=0;m<6;m++){
      const left=col(m*2),right=col(m*2+1);
      const [year,month]=r.obs_start_month.split('-').map(Number);
      const offset=year*12+month-1+m;
      const expected=m<r.cover_month_cnt?`${Math.floor(offset/12)}-${String(offset%12+1).padStart(2,'0')}`:null;
      const e=entries.find(item=>item.obs_month===expected);
      text(months,`${left}${first+1}:${right}${first+1}`,expected||'',26);
      months.getRange(`${left}${first+1}:${right}${first+1}`).format={fill:COLOR.section,font:{name:'Microsoft YaHei',size:11,bold:true,color:COLOR.navy},horizontalAlignment:'center'};
      text(months,`${left}${first+2}:${right}${first+2}`,e?numeric(e.month_amount):expected?'未提供':null,30);
      months.getRange(`${left}${first+2}:${right}${first+2}`).setNumberFormat(MONEY);months.getRange(`${left}${first+2}:${right}${first+2}`).format.horizontalAlignment='center';
      text(months,`${left}${first+3}:${right}${first+3}`,e?`${e.anchor_day}日 / ${e.pay_cnt}笔 / 窗口${(numeric(e.window_ratio)*100).toFixed(1)}%`:expected?'证据缺失':'',30);
    }
    text(months,`M${first+1}:P${first+3}`,`${mock?'模拟数据。':''}上游主要规则${r.main_rule}，覆盖${r.cover_month_cnt}月，金额波动率${(numeric(r.volatility)*100).toFixed(1)}%，最低窗口占比${(numeric(r.min_window_ratio)*100).toFixed(1)}%。${entries.length!==r.cover_month_cnt?'证据月份不足，相关结论待核对。':''}`,30);
  });
  if(!workers.length)section(months,'A1:P1','月度证据 当前范围无人员预警记录');
  const evidenceTitle=Math.max(3,workers.length*6+1),eh=evidenceTitle+1;
  section(months,`A${evidenceTitle}:Q${evidenceTitle}`,'月度证据完整明细 按预警ID关联，保留全部17个SQL字段');
  const fields=['warn_id','customer_id','worker_id','currency','obs_month','obs_month_seq','has_pay_flag','month_amount','pay_cnt','anchor_day','window_start','window_end','window_amount','window_ratio','rule_version','ds','etl_time'];
  const eb=table(months,eh,['预警ID','客户ID','灵工ID','币种','月份','月序','有效发放标志','月金额(元)','发放笔数','当月锚定日','窗口起始日','窗口截止日','窗口金额(元)','窗口占比','规则版本','评估批次ds','更新时间'],
    evidence.map(r=>fields.map(k=>['month_amount','window_amount','window_ratio'].includes(k)?numeric(r[k]):k==='etl_time'?dateValue(r[k]):literal(r[k]))),'MonthlyEvidence',
    {F:INT,H:MONEY,I:INT,J:INT,K:INT,L:INT,M:MONEY,N:RATE,Q:DATETIME});
  months.getRange(`A${eh}:Q${eb}`).format.wrapText=true;months.getRange(`A${eh+1}:Q${eb}`).format.rowHeight=44;
  text(months,`A${eb+2}:Q${eb+2}`,'不同客户的同一灵工分别识别；缺月不能用零补齐。规则命中为疑似固定用工特征，不能据此确认历史员工身份或劳务转灵工事实。',34);

  write(main,'A3',mock?'模拟演示数据。每条人员预警对应客户＋灵工＋币种，同一灵工在不同客户下分别识别。':'每条人员预警对应客户＋灵工＋币种；本报告仅覆盖本次接口返回范围。');main.getRange('A3:P3').format.rowHeight=30;
  write(main,'C4',customers.length?new Date(`${customers[0].ds.slice(0,4)}-${customers[0].ds.slice(4,6)}-${customers[0].ds.slice(6,8)}T00:00:00Z`):'未提供');main.getRange('C4').setNumberFormat('yyyy-mm-dd');main.getRange('C4').format.wrapText=false;main.getRange('C4').format.horizontalAlignment='center';
  const periods=[...new Set(customers.map(r=>`${r.obs_start_month}至${r.obs_end_month}`))];
  write(main,'F4',`${periods.join('；')||'未提供'}；R02见人员6月观察期`);write(main,'M4',`${customers[0]?.rule_version||'未提供'} / ${currencies.join('、')||'未提供'}`);
  main.getRange('F4:J4').format.wrapText=true;main.getRange('M4:P4').format.wrapText=true;
  write(main,'A5',issues.length?`数据存在${issues.length}项核对异常，相关结论待核对，详见下方。`:customers.length?'本次返回范围三表一致性校验通过。预警为疑似线索，不自动阻断发放。':'当前响应无已评估客户，不能据此推断全部客户无风险。');main.getRange('A5:P5').format.rowHeight=30;
  if(issues.length)main.getRange('A5:P5').format.fill=COLOR.red;
  write(main,'A7',new Set(customers.map(r=>r.customer_id)).size);
  formula(main,'D7',`=COUNTIF('客户风险汇总'!H3:H${cb},"R03命中")`);formula(main,'G7',`=COUNTA('命中人员明细'!A3:A${wbott})`);formula(main,'J7',`=COUNTIF('命中人员明细'!F3:F${wbott},"R02")`);
  write(main,'M6',currencies.length===1?`涉及金额（近3月，${currencies[0]}元）`:'涉及金额（按币种分别统计）');
  if(currencies.length===1){formula(main,'M7',`=SUM('客户风险汇总'!G3:G${cb})`);main.getRange('M7:P7').setNumberFormat(MONEY);}else write(main,'M7',currencies.length?'见下方分币种金额':'无记录');
  main.getRange('A7:P7').format.rowHeight=32;
  section(main,'A10:P10','金额统计 客户全量金额包含预警人员部分，二者不可相加');
  text(main,'A11:B11','币种');text(main,'C11:I11','客户全部有效金额（元）');text(main,'J11:P11','其中预警人员近3月金额（元）');
  main.getRange('A11:P11').format.fill=COLOR.navy;main.getRange('A11:P11').format.font={name:'Microsoft YaHei',size:11,bold:true,color:'#FFFFFF'};
  currencies.forEach((currency,i)=>{const row=12+i;text(main,`A${row}:B${row}`,currency);main.getRange(`C${row}:I${row}`).merge();main.getRange(`J${row}:P${row}`).merge();
    formula(main,`C${row}`,`=SUMIF('客户风险汇总'!J3:J${cb},A${row},'客户风险汇总'!G3:G${cb})`);formula(main,`J${row}`,`=SUMIF('命中人员明细'!Q3:Q${wbott},A${row},'命中人员明细'!J3:J${wbott})`);main.getRange(`C${row}:P${row}`).setNumberFormat(MONEY);});
  const issueTitle=14+currencies.length;
  section(main,`A${issueTitle}:P${issueTitle}`,'数据核对与报告边界');
  const notes=[...issues,'原流水、员工名单、社保、考勤、合同、任务单及后续措施未提供；锚点枚举最优性需另调源流水核实。','规则命中仅为疑似固定用工线索，不认定历史员工身份或劳务转灵工事实。客户与人员的黄色字段分别维护核查信息。'];
  notes.forEach((line,i)=>text(main,`A${issueTitle+1+i}:P${issueTitle+1+i}`,line,34));if(issues.length)main.getRange(`A${issueTitle+1}:P${issueTitle+issues.length}`).format.fill=COLOR.red;
  wb.recalculate();
  const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:50},maxChars:3000});
  if(/"kind":"match"/.test(errors.ndjson))throw new Error(`工作簿公式错误：${errors.ndjson}`);
  const checks={main:(await wb.inspect({kind:'table',range:`${SHEETS[0]}!A6:P7`,tableMaxRows:2,tableMaxCols:16,maxChars:3000})).ndjson,
    formulaErrors:errors.ndjson,formula_error_count:0,sheets:SHEETS,
    amounts_by_currency:Object.fromEntries(currencies.map((currency,i)=>[currency,{customer_involved_amount:main.getRange(`C${12+i}`).values[0][0],warned_worker_amount_3m:main.getRange(`J${12+i}`).values[0][0]}])),
    rows:{customers:customers.length,workers:workers.length,evidence:evidence.length},dataIssues:issues,layout:{customer_parameter_header:ph,evidence_header:eh}};
  if(previewDir){await fs.mkdir(previewDir,{recursive:true});
    for(const [sheetName,range,name]of [[SHEETS[0],`A1:P${issueTitle+notes.length}`,'report'],[SHEETS[1],`A1:P${pb}`,'customers'],[SHEETS[2],`A1:P${Math.min(wbott+2,12)}`,'workers'],[SHEETS[3],`A1:P${Math.min(12,evidenceTitle)}`,'evidence']]){const png=await wb.render({sheetName,range,scale:1.3,format:'png'});await fs.writeFile(path.join(previewDir,`${name}.png`),new Uint8Array(await png.arrayBuffer()));}
    await fs.writeFile(path.join(previewDir,'checks.json'),JSON.stringify(checks,null,2));}
  await fs.mkdir(path.dirname(output),{recursive:true});const pending=output.replace(/\.xlsx$/i,`.pending-${process.pid}.xlsx`);
  try{await(await SpreadsheetFile.exportXlsx(wb)).save(pending);await fs.rename(pending,output);}finally{await fs.rm(pending,{force:true});await fs.rm(`${pending}.inspect.ndjson`,{force:true});}
  if(checksFile)await fs.writeFile(checksFile,JSON.stringify(checks));console.log(JSON.stringify(checks));
}
try{await fill(JSON.parse(await fs.readFile(process.argv[2],'utf8')));}catch(error){console.error(error.stack||String(error));process.exitCode=2;}
