import {parquetSchema, type SchemaElement} from 'hyparquet';
import {retainedBytes} from './cache.ts';

const temporalValue=Symbol('archive.temporal');
export interface ArchiveDateValue {type:'date'; days:number; readonly [temporalValue]:'date'}
export interface ArchiveTimestampValue {type:'timestamp'; unit:'ms'|'us'|'ns'; value:bigint; readonly [temporalValue]:'timestamp'}
export const isArchiveDateValue=(value:unknown):value is ArchiveDateValue=>Boolean(value&&typeof value==='object'&&(value as any)[temporalValue]==='date');
export const isArchiveTimestampValue=(value:unknown):value is ArchiveTimestampValue=>Boolean(value&&typeof value==='object'&&(value as any)[temporalValue]==='timestamp');
const dateValue=(days:number):ArchiveDateValue=>Object.defineProperty({type:'date',days},temporalValue,{value:'date'}) as ArchiveDateValue;
const timestampValue=(unit:ArchiveTimestampValue['unit'],value:bigint):ArchiveTimestampValue=>Object.defineProperty({type:'timestamp',unit,value},temporalValue,{value:'timestamp'}) as ArchiveTimestampValue;
export type ArchiveRawValue = null|boolean|number|bigint|string|Uint8Array|ArchiveDateValue|ArchiveTimestampValue|ArchiveRawValue[]|{[name:string]:ArchiveRawValue};
export interface ArchiveReadRowsOptions {offset?:number; limit?:number; maxBytes?:number; signal?:AbortSignal}
export interface ArchiveRowsPage {
  releaseId:string;
  file:{name:string; sha256:string; size:number; rows:number; rowRange:[number,number]};
  offset:number;
  totalRows:number;
  nextOffset:number|null;
  schema:SchemaElement[];
  rows:Record<string,ArchiveRawValue>[];
  rowPositions:{row:number; fileRow:number}[];
}
export class ArchiveRowsError extends Error {
  readonly code:'INVALID_PAGE'|'UNAVAILABLE'|'UNSUPPORTED_TYPE'|'SCHEMA_MISMATCH'|'BUDGET_EXCEEDED';
  constructor(code:ArchiveRowsError['code'], message:string) {
    super(message); this.name='ArchiveRowsError';this.code=code;
  }
}

export const rawParsers = {
  dateFromDays:dateValue,
  timestampFromMilliseconds:(value:bigint):ArchiveTimestampValue=>timestampValue('ms',value),
  timestampFromMicroseconds:(value:bigint):ArchiveTimestampValue=>timestampValue('us',value),
  timestampFromNanoseconds:(value:bigint):ArchiveTimestampValue=>timestampValue('ns',value),
};

/** This reader's supported physical types, not a second dataset definition owner. */
export function checkRawSchema(metadata:any, definition:any):void {
  const converted=new Set(['UTF8','LIST','DATE','TIMESTAMP_MILLIS','TIMESTAMP_MICROS','INT_8','INT_16','INT_32','INT_64','UINT_8','UINT_16','UINT_32','UINT_64']);
  const logical=new Set(['STRING','LIST','DATE','TIMESTAMP','INTEGER']);
  for(const field of metadata.schema) {
    if(field.name==='__proto__'||field.name.includes('.'))throw new ArchiveRowsError('UNSUPPORTED_TYPE',`The pinned decoder cannot preserve the field name ${field.name}.`);
    if(field.type==='INT96'||field.converted_type&&!converted.has(field.converted_type)||field.logical_type&&!logical.has(field.logical_type.type)) {
      throw new ArchiveRowsError('UNSUPPORTED_TYPE',`Raw rows cannot preserve ${field.logical_type?.type??field.converted_type??field.type} in ${field.name}.`);
    }
    if(['DATE','LIST'].includes(field.logical_type?.type)&&field.converted_type!==field.logical_type.type)
      throw new ArchiveRowsError('UNSUPPORTED_TYPE',`The pinned decoder needs the converted ${field.logical_type.type} annotation in ${field.name}.`);
    const compatible=({UTF8:'STRING',LIST:'LIST',DATE:'DATE',TIMESTAMP_MILLIS:'TIMESTAMP',TIMESTAMP_MICROS:'TIMESTAMP'} as any)[field.converted_type]
      ??(/^(U?INT)_/.test(field.converted_type??'')?'INTEGER':undefined);
    if(field.logical_type&&field.converted_type&&(field.logical_type.type!==compatible
      ||compatible==='TIMESTAMP'&&(field.logical_type.unit!==field.converted_type.slice(10)||field.logical_type.isAdjustedToUTC!==true)
      ||compatible==='INTEGER'&&(field.logical_type.bitWidth!==Number(field.converted_type.split('_')[1])||field.logical_type.isSigned!==field.converted_type.startsWith('INT_'))))
      throw new ArchiveRowsError('SCHEMA_MISMATCH',`Contradictory Parquet annotations in ${field.name}.`);
  }
  const mismatch=(path:string)=>{throw new ArchiveRowsError('SCHEMA_MISMATCH',`Parquet field schema differs from the catalog: ${path}.`);};
  const children=(nodes:any[], definitions:any[], path:string, depth:number)=>{
    if(depth>32)throw new ArchiveRowsError('UNSUPPORTED_TYPE','Raw row nesting exceeds the supported depth.');
    const names=definitions.map(field=>field.physicalName??field.name);
    if(nodes.length!==names.length||new Set(names).size!==names.length||new Set(nodes.map(node=>node.element.name)).size!==names.length||nodes.some(node=>!names.includes(node.element.name)))mismatch(path);
    for(const node of nodes)check(node,definitions[names.indexOf(node.element.name)],`${path}.${node.element.name}`,depth);
  };
  const check=(node:any, authored:any, path:string, depth:number)=>{
    if(depth>32)throw new ArchiveRowsError('UNSUPPORTED_TYPE','Raw row nesting exceeds the supported depth.');
    const e=node.element, logicalType=e.logical_type?.type, convertedType=e.converted_type;
    if(e.repetition_type==='REPEATED')mismatch(path);
    if(authored.logicalType==='array') {
      if(logicalType!=='LIST'&&convertedType!=='LIST'||node.children.length!==1||node.children[0].element.repetition_type!=='REPEATED'||node.children[0].children.length!==1||!authored.items)mismatch(path);
      check(node.children[0].children[0],authored.items,`${path}[]`,depth+1);
      return;
    }
    if(authored.logicalType==='object') {
      if(e.type||logicalType||convertedType||!Array.isArray(authored.properties))mismatch(path);
      children(node.children,authored.properties,path,depth+1);return;
    }
    if(node.children.length)mismatch(path);
    const type=authored.physicalType;
    let matches=false;
    if(type==='dict'||type==='string')matches=e.type==='BYTE_ARRAY'&&(convertedType==='UTF8'||logicalType==='STRING');
    else if(type==='bool'||type==='boolean')matches=e.type==='BOOLEAN'&&!logicalType&&!convertedType;
    else if(type==='date32')matches=e.type==='INT32'&&(convertedType==='DATE'||logicalType==='DATE');
    else if(/^fixed\[\d+\]$/.test(type))matches=e.type==='FIXED_LEN_BYTE_ARRAY'&&e.type_length===Number(type.slice(6,-1))&&!logicalType&&!convertedType;
    else if(type==='binary')matches=e.type==='BYTE_ARRAY'&&!logicalType&&!convertedType;
    else if(/^(u?int)(8|16|32|64)$/.test(type)) {
      const bits=Number(type.match(/\d+/)[0]), signed=!type.startsWith('u');
      matches=e.type===(bits===64?'INT64':'INT32')&&(
        logicalType==='INTEGER'?e.logical_type.bitWidth===bits&&e.logical_type.isSigned===signed:
        convertedType?convertedType===`${signed?'INT':'UINT'}_${bits}`:signed&&(bits===32||bits===64));
    } else if(type==='float32'||type==='float64')matches=e.type===(type==='float32'?'FLOAT':'DOUBLE')&&!logicalType&&!convertedType;
    else if(/^timestamp<(millisecond|microsecond|nanosecond)(,UTC)?>$/.test(type)) {
      const unit=type.includes('millisecond')?'MILLIS':type.includes('microsecond')?'MICROS':'NANOS';
      matches=e.type==='INT64'&&(logicalType==='TIMESTAMP'?e.logical_type.unit===unit&&e.logical_type.isAdjustedToUTC===type.endsWith(',UTC>'):
        convertedType===`TIMESTAMP_${unit}`&&type.endsWith(',UTC>'));
    } else throw new ArchiveRowsError('UNSUPPORTED_TYPE',`Raw rows do not support the declared physical type ${type} at ${path}.`);
    if(!matches)mismatch(path);
  };
  if(!Array.isArray(definition?.properties))mismatch('root');
  children(parquetSchema(metadata).children,definition.properties,'root',0);
}

/** Admit every intersecting physical group before the decoder allocates it.
 * These are conservative allocation estimates, not a JavaScript heap guarantee.
 */
export function rawDecodeBytes(metadata:any, start:number, end:number):number {
  const quantity=(value:any)=>{
    const n=Number(value);
    if(value==null||!Number.isSafeInteger(n)||n<0)throw new ArchiveRowsError('BUDGET_EXCEEDED','Raw row metadata has unsafe allocation counts.');
    return n;
  };
  const depths=new Map<string,number>();
  const visit=(node:any)=>{
    if(node.children.length)node.children.forEach(visit);
    else depths.set(JSON.stringify(node.path),node.path.length);
  };
  parquetSchema(metadata).children.forEach(visit);
  let position=0, bytes=0;
  for(const group of metadata.row_groups) {
    const rows=quantity(group.num_rows), stop=position+rows;
    if(start<stop&&end>position) {
      // Column/range copies, level/value arrays and nested row containers coexist.
      bytes+=rows*metadata.schema.length*32;
      for(const column of group.columns) {
        if(!column.meta_data)throw new ArchiveRowsError('BUDGET_EXCEEDED','Raw row metadata omits a column allocation.');
        const depth=depths.get(JSON.stringify(column.meta_data.path_in_schema));
        if(!depth)throw new ArchiveRowsError('SCHEMA_MISMATCH','Raw row metadata has an unknown physical column path.');
        bytes+=quantity(column.meta_data.total_compressed_size)*2+quantity(column.meta_data.total_uncompressed_size)*4
          +quantity(column.meta_data.num_values)*(64+depth*96);
      }
    }
    if(!Number.isSafeInteger(stop)||!Number.isSafeInteger(bytes))throw new ArchiveRowsError('BUDGET_EXCEEDED','Raw row allocation estimate is unsafe.');
    position=stop;
  }
  if(position!==quantity(metadata.num_rows))throw new ArchiveRowsError('SCHEMA_MISMATCH','Parquet row groups differ from the declared row count.');
  return bytes;
}

/** Detach binary cells from decoder page buffers; make nested Parquet null explicit. */
export function ownRawValue(value:any):ArchiveRawValue {
  if(value==null)return null;
  if(isArchiveDateValue(value))return dateValue(value.days);
  if(isArchiveTimestampValue(value))return timestampValue(value.unit,value.value);
  if(value instanceof Uint8Array)return value.slice();
  if(Array.isArray(value))return value.map(ownRawValue);
  if(typeof value==='object')return Object.fromEntries(Object.entries(value).map(([name,child])=>[name,ownRawValue(child)]));
  return value;
}

/** Statistics may be tiny views into a complete footer read. Keep only their bytes. */
export function detachRawMetadata(metadata:any):any {
  const detached=new Map<object,any>();
  const visit=(value:any):any=>{
    if(value==null||typeof value!=='object'||value instanceof Date)return value;
    if(detached.has(value))return detached.get(value);
    if(value instanceof Uint8Array){const copy=value.slice();detached.set(value,copy);return copy;}
    detached.set(value,value);
    for(const key of Object.keys(value))value[key]=visit(value[key]);
    return value;
  };
  return visit(metadata);
}

export function rawOutputBytes(page:ArchiveRowsPage):number {return retainedBytes(page);}
