import fs from 'node:fs/promises';
import path from 'node:path';
import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';

const NAMES=['灵工固定用工特征风控报告','客户风险汇总','命中人员明细','月度证据'];
const COLOR={navy:'#223B57'};
const TABLE_BORDER={style:'thin',color:'#B0B7C0'};
const EVIDENCE_FILLS=['#FFFFFF','#EBEDF0'];
const column=n=>{let s='';for(n++;n>0;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s;};
const literal=v=>typeof v==='string'&&/^[=+@-]/.test(v)?`'${v}`:v;
const scalar=v=>v===null?'未提供':typeof v==='object'?literal(JSON.stringify(v)):literal(v);
function write(s,cell,v){s.getRange(cell).values=[[literal(v)]];}
function columnsFor(rows){const keys=new Set();for(const row of rows)for(const key of Object.keys(row))keys.add(key);return [...keys];}
function rawTable(s,start,job,name,view){
  const keys=view.columns;
  const evidenceView=Boolean(view.groups);
  const blankColumns=view.blankColumns ?? [];
  const last=column(Math.max(keys.length,1)-1);
  const bottom=start+Math.max(job.rows.length,1);
  if(keys.length>16384||bottom>1048576)throw new Error('结果超出Excel单表行列上限，请先拆分请求范围');
  // Prefix only colliding case-insensitive names, since Excel table headers must be unique.
  const labels=keys.map(k=>view.headers?.[k] ?? k);
  const counts=new Map();for(const k of labels)counts.set(k.toLowerCase(),(counts.get(k.toLowerCase())||0)+1);
  const headers=labels.map((k,i)=>literal(counts.get(k.toLowerCase())>1?`[${i+1}] ${k}`:k));
  const rows=job.rows.map(row=>keys.map(k=>displayValue(row,k,blankColumns)));
  for(const row of rows)for(const value of row)if(typeof value==='string'&&value.length>32767)throw new Error('单元格文本超过Excel上限，不能截断生成');
  s.getRange(`A${start}:${last}${bottom}`).values=[headers,...(rows.length?rows:[Array(keys.length).fill(null)])];
  if(!evidenceView&&job.rows.length){
    const table=s.tables.add(`A${start}:${last}${bottom}`,true,name);table.style='TableStyleMedium2';table.showFilterButton=true;
  }
  s.getRange(`A${start}:${last}${start}`).format={fill:COLOR.navy,font:{name:'Microsoft YaHei',size:11,bold:true,color:'#FFFFFF'},wrapText:true,horizontalAlignment:'center',rowHeight:48};
  if(!evidenceView){
    s.getRange(`A${start}:${last}${start+rows.length}`).format.borders={preset:'all',...TABLE_BORDER};
  }
  s.getRange(`A${start+1}:A${bottom}`).format.rowHeight=40;
  keys.forEach((key,i)=>{
    const letter=column(i);
    s.getRange(`${letter}:${letter}`).format.columnWidth=view.columnWidths?.[key] ?? (/time|date|table|name|conclusion|basis/i.test(key)?30:24);
    const format=view.numberFormats?.[key];
    if(format)s.getRange(`${letter}${start+1}:${letter}${bottom}`).setNumberFormat(format);
  });
  return {header:start,bottom,keys,blankColumns};
}

function displayValue(row,key,blankColumns){
  if(blankColumns.includes(key))return null;
  return Object.hasOwn(row,key)?scalar(row[key]):'未提供';
}

async function fill(request){
  const {results,layout,mock,template,output,checksFile,previewDir}=request;
  const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(template));
  const info=await wb.inspect({kind:'sheet',include:'id,name',maxChars:4000});
  const names=info.ndjson.trim().split('\n').filter(Boolean).map(s=>JSON.parse(s).name);
  if(JSON.stringify(names)!==JSON.stringify(NAMES))throw new Error('模板须保留新版四个工作表');
  const [main,customers,workers,evidence]=NAMES.map(name=>wb.worksheets.getItem(name));
  const jobs=results.jobs;
  const workerJob=jobs[layout.worker];
  const customerJob=jobs[layout.customer];
  const evidenceJob=jobs[layout.evidence];
  const orderedJobs=[workerJob,customerJob,evidenceJob];
  for(const s of [main,customers,workers,evidence])s.freezePanes.unfreeze();
  for(const s of [customers,workers,evidence]){
    for(const t of [...s.tables.items])t.delete();
    const used=s.getUsedRange();used.unmerge();used.conditionalFormats.clear();used.dataValidation=null;used.clear({applyTo:'all'});
    s.getRange('A:P').format.columnWidth=14;s.showGridLines=false;
  }
  main.getRange('A3:P8').clear({applyTo:'contents'});main.showGridLines=false;
  main.getRange('A:P').format.columnWidth=12;
  write(main,'A2','灵工固定用工特征风控报告 执行结果');
  write(main,'A3',mock?'模拟数据验收报告；按任务分别展示原始结果。':'按任务分别展示原始执行结果。');main.getRange('A3:P3').format.rowHeight=32;
  write(main,'A4','报告日期');write(main,'D4','观察期');write(main,'K4','规则版本');
  const metadata=layout.summaryMetadata;
  write(main,'C4',metadata?.reportDate ?? '未提供');
  write(main,'F4',metadata?.period ?? 'R01近3月；R02近6月；具体起止月见上游字段');
  write(main,'M4',metadata?.rule ?? '见上游结果字段');
  main.getRange('A4:P4').format.rowHeight=44;
  const date=main.getRange('C4').format;
  date.wrapText=true;date.horizontalAlignment='center';date.verticalAlignment='center';
  main.getRange('F4:J4').format.wrapText=true;main.getRange('M4:P4').format.wrapText=true;
  write(main,'A5','分页、文件完整性与任务身份校验通过。');main.getRange('A5:P5').format.rowHeight=32;
  const metrics=layout.summaryMetrics;
  metrics.forEach(([label,value],index)=>{
    const cell='ADGJM'[index];write(main,`${cell}6`,label);write(main,`${cell}7`,value);
  });
  main.getRange('A6:P6').format.rowHeight=36;main.getRange('A6:P6').format.wrapText=true;main.getRange('A7:P7').format.rowHeight=32;
  const ranges=['A2:P2','A3:P3','A4:B4','C4','D4:E4','F4:J4','K4:L4','M4:P4','A5:P5'];
  for(const row of [6,7]){
    for(const [left,right] of [['A','C'],['D','F'],['G','I'],['J','L'],['M','P']]){
      ranges.push(`${left}${row}:${right}${row}`);
    }
  }
  for(const address of ranges)main.getRange(address).format.borders={preset:'outside',...TABLE_BORDER};
  const headerRow=layout.headerRow;
  const customerLayout=rawTable(customers,headerRow,customerJob,'CustomerResults',layout.customerView);
  const workerLayout=rawTable(workers,headerRow,workerJob,'WorkerResults1',layout.workerView);
  const evidenceLayout=rawTable(evidence,headerRow,evidenceJob,'MonthlyEvidence',layout.evidenceView);
  const rawSections=[[customers,customerLayout,customerJob],[workers,workerLayout,workerJob],[evidence,evidenceLayout,evidenceJob]];
  for(const address of Object.keys(layout.workerLinks ?? {})){
    workers.getRange(address).format.font.color='#0563C1';
  }
  wb.recalculate();
  const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:50},maxChars:2000});
  if(/"kind":"match"/.test(errors.ndjson))throw new Error(`公式错误或上游错误字面值：${errors.ndjson}`);
  // Read back every exported raw cell, including sparse fields and formula-like strings.
  for(const [s,layout,job]of rawSections){
    if(!job.rows.length)continue;
    const values=s.getRange(`A${layout.header+1}:${column(layout.keys.length-1)}${layout.bottom}`).values;
    const formulas=s.getRange(`A${layout.header+1}:${column(layout.keys.length-1)}${layout.bottom}`).formulas;
    job.rows.forEach((row,i)=>layout.keys.forEach((key,j)=>{
      const expected=displayValue(row,key,layout.blankColumns);
      const value=values[i][j];
      if(value!==expected&&!(typeof expected==='string'&&expected.startsWith("'")&&value===expected.slice(1)))throw new Error(`原始结果写入校验失败：${job.bizKey}/${i}/${key}`);
      if(formulas[i]?.[j])throw new Error(`数据被误写为公式：${job.bizKey}/${i}/${key}`);
    }));
  }
  const {columns,identityColumns,groups}=layout.evidenceView;
  const last=column(columns.length-1);
  evidence.getRange(`A${headerRow}:${last}${headerRow}`).format.borders={preset:'all',...TABLE_BORDER};
  for(const [groupIndex,[first,end]] of groups.entries()){
    const top=headerRow+first+1,bottom=headerRow+end;
    const group=evidence.getRange(`A${top}:${last}${bottom}`);
    for(let index=0;index<identityColumns;index++){
      const letter=column(index);
      const range=evidence.getRange(`${letter}${top}:${letter}${bottom}`);
      if(top!==bottom)range.merge();
      range.format.borders={preset:'outside',...TABLE_BORDER};
    }
    group.format.fill=EVIDENCE_FILLS[groupIndex%2];
    group.format.verticalAlignment='center';
    evidence.getRange(`${column(identityColumns)}${top}:${last}${bottom}`).format.borders={preset:'all',...TABLE_BORDER};
  }
  const checks={rows_by_biz_key:Object.fromEntries(orderedJobs.map(job=>[job.bizKey,job.rows.length])),formula_error_count:0,
    business_mapping_verified:false,monthly_evidence_available:Boolean(evidenceJob.rows.length),
    columns_by_biz_key:Object.fromEntries(orderedJobs.map(job=>[job.bizKey,columnsFor(job.rows)]))};
  if(previewDir){await fs.mkdir(previewDir,{recursive:true});
    let evidenceLastRow=Math.min(evidenceLayout.bottom,16);
    const evidenceLastColumn=last;
    const clippedGroup=groups.find(([first,end])=>headerRow+first<evidenceLastRow&&headerRow+end>evidenceLastRow);
    if(clippedGroup)evidenceLastRow=headerRow+clippedGroup[1];
    for(const [sheetName,range,name]of [[NAMES[0],'A1:P7','report'],[NAMES[1],`A1:P${Math.min(customerLayout.bottom,10)}`,'customers'],[NAMES[2],`A1:${column(workerLayout.keys.length-1)}${Math.min(workerLayout.bottom,18)}`,'workers'],[NAMES[3],`A1:${evidenceLastColumn}${evidenceLastRow}`,'evidence']]){
      const png=await wb.render({sheetName,range,scale:1.2,format:'png'});await fs.writeFile(path.join(previewDir,`${name}.png`),new Uint8Array(await png.arrayBuffer()));
    }
  }
  await fs.mkdir(path.dirname(output),{recursive:true});const pending=output.replace(/\.xlsx$/i,`.pending-${process.pid}.xlsx`);
  try{await(await SpreadsheetFile.exportXlsx(wb)).save(pending);await fs.rename(pending,output);}finally{await fs.rm(pending,{force:true});await fs.rm(`${pending}.inspect.ndjson`,{force:true});}
  await fs.writeFile(checksFile,JSON.stringify(checks));
}
try{await fill(JSON.parse(await fs.readFile(process.argv[2],'utf8')));}catch(error){console.error(error.stack||String(error));process.exitCode=2;}
