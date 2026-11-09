import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import TrainingDatasetSelector from '../TrainingDatasetSelector';

afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it('keeps a catalog check failure distinct and retries reads only',async()=>{
 let fail=true;
 const transport=vi.fn(async()=>{if(fail)throw new TypeError('offline');return Response.json({datasets:[]});});vi.stubGlobal('fetch',transport);
 render(<TrainingDatasetSelector includeImported={false} onSelect={vi.fn()}/>);
 expect((await screen.findByRole('alert')).textContent).toContain('Error de comprobación');
 fail=false;fireEvent.click(screen.getByRole('button',{name:'Reintentar consulta'}));
 await screen.findByText('No hay datasets que coincidan con la búsqueda.');
 expect(transport).toHaveBeenCalledTimes(2);
 expect(transport.mock.calls.every(call=>(call as unknown as [string,RequestInit])[1]?.method==='GET')).toBe(true);
});
it('lists mixed sources and duplicate names with stable identities and preserves selection while searching',async()=>{
 let fail=false;
 vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>{
  if(fail)throw new TypeError('offline');
  return Response.json({datasets:String(input).includes('include_unavailable')?[
  {id:'Smoke',name:'Smoke',record_id:'legacy:7',source_type:'legacy',audio_count:9,class_count:3,eligible:true,eligibility_state:'current_flow_compatible',reasons:[]},
  {id:'MaquinariaMinas',name:'MaquinariaMinas',record_id:'legacy:8',source_type:'legacy',audio_count:0,class_count:null,eligible:false,eligibility_state:'blocked',reasons:['incompatible_configuration']},
 ]:[{id:'own',name:'Smoke',source_type:'imported',eligible:false,reasons:['preparation_required'],preparations:[]}]});}));
 const select=vi.fn();const view=render(<TrainingDatasetSelector includeImported onSelect={select}/>);
 expect(screen.queryByLabelText('Buscar dataset por nombre')).toBeNull();
 const trigger=screen.getByRole('combobox',{name:'Dataset para entrenamiento'});
 expect(trigger.textContent).toBe('Buscar o seleccionar dataset…');
 fireEvent.click(trigger);
 expect(screen.getByPlaceholderText('Buscar dataset por nombre…')).toBe(screen.getByLabelText('Buscar dataset por nombre'));
 await screen.findByRole('option',{name:/MaquinariaMinas/});
 const choices=screen.getAllByRole('option',{name:/Smoke/});expect(choices).toHaveLength(2);
 expect(choices.map(o=>o.textContent)).toEqual(['Smoke — Compartido','Smoke — Privado']);
 fireEvent.mouseEnter(choices[1]);
 expect(screen.getByLabelText('Buscar dataset por nombre').getAttribute('aria-activedescendant')).toBe(choices[1].id);
 expect(choices[1].classList.contains('bg-[#23252e]')).toBe(true);
 expect(choices[0].classList.contains('bg-[#23252e]')).toBe(false);
 expect(select).not.toHaveBeenCalled();
 expect(screen.queryByText(/legacy:7|imported:own/)).toBeNull();
 fireEvent.click(screen.getByRole('option',{name:'Smoke — Privado'}));
 expect(select).toHaveBeenLastCalledWith(expect.objectContaining({source_type:'imported',id:'own'}));
 fireEvent.keyDown(trigger,{key:'ArrowDown'});
 const search=screen.getByLabelText('Buscar dataset por nombre');
 expect(document.activeElement).toBe(search);
 fireEvent.change(search,{target:{value:'mAqUiNaRiA'}});
 expect(screen.getAllByRole('option',{name:/MaquinariaMinas/})).toHaveLength(1);
 fireEvent.keyDown(search,{key:'Escape'});
 expect(trigger.textContent).toContain('Smoke — Privado');
 expect(document.activeElement).toBe(trigger);
 expect(select).toHaveBeenCalledTimes(1);
 fireEvent.click(trigger);
 const keyboardSearch=screen.getByLabelText('Buscar dataset por nombre');
 fireEvent.change(keyboardSearch,{target:{value:'Smoke'}});
 fireEvent.keyDown(keyboardSearch,{key:'ArrowDown'});
 fireEvent.keyDown(keyboardSearch,{key:'ArrowUp'});
 fireEvent.keyDown(keyboardSearch,{key:'Enter'});
 expect(select).toHaveBeenLastCalledWith(expect.objectContaining({source_type:'legacy',record_id:'legacy:7'}));
 expect(trigger.textContent).toBe('Smoke — Compartido');
 expect(document.activeElement).toBe(trigger);
 // A read failure/retry never changes the user's choice.
 fail=true;view.rerender(<TrainingDatasetSelector includeImported={false} onSelect={select}/>);
 await screen.findByRole('alert');
 fail=false;fireEvent.click(screen.getByRole('button',{name:'Reintentar consulta'}));
 await waitFor(()=>expect(screen.queryByRole('alert')).toBeNull());
 expect(trigger.textContent).toBe('Smoke — Compartido');
 expect(select).toHaveBeenCalledTimes(2);
 fireEvent.click(trigger);
 fireEvent.blur(screen.getByLabelText('Buscar dataset por nombre'),{relatedTarget:null});
 expect(trigger.getAttribute('aria-expanded')).toBe('false');
 view.rerender(<TrainingDatasetSelector includeImported={false} disabled onSelect={select}/>);
 expect((trigger as HTMLButtonElement).disabled).toBe(true);
 fireEvent.click(trigger);fireEvent.keyDown(trigger,{key:'ArrowDown'});
 expect(screen.queryByLabelText('Buscar dataset por nombre')).toBeNull();
 expect(select).toHaveBeenCalledTimes(2);
});
