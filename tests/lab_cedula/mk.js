// Las 3 líneas sintéticas (con sus dígitos de control) que dibuja gen.py.
const fs=require('fs');const src=fs.readFileSync(require('path').join(__dirname,'..','..','static','js','cedula-readers.js'),'utf8');
const a=src.indexOf('function mrzCheck'), b=src.indexOf('/* ---------- geometría pura');
const {mrzCheck}=new Function(src.slice(a,b)+';return {mrzCheck};')();
const pad=(s,n)=>(s+'<'.repeat(n)).slice(0,n);
const doc='000123456',birth='900515',sex='F',exp='320101',ced='1013259208',names='RAMIREZ<TORRES<<JUAN<DAVID';
const l1=pad('ICCOL'+doc+mrzCheck(doc)+'12345',30),opt2=pad(ced+'<',11),core=birth+mrzCheck(birth)+sex+exp+mrzCheck(exp)+'COL'+opt2;
const comp=mrzCheck(l1.slice(5,30)+core.slice(0,7)+core.slice(8,15)+opt2);
console.log(JSON.stringify([l1,core+comp,pad(names,30)]));
