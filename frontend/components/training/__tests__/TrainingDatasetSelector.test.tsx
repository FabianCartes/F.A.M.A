import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import TrainingDatasetSelector from '../TrainingDatasetSelector';

afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it('keeps a catalog check failure distinct and retries reads only',async()=>{
 let fail=true;
 const transport=vi.fn(async()=>{if(fail)throw new TypeError('offline');return Response.json({datasets:[]});});vi.stubGlobal('fetch',transport);
 render(<TrainingDatasetSelector onSelect={vi.fn()}/>);
 expect((await screen.findByRole('alert')).textContent).toContain('Error de comprobación');
 fail=false;fireEvent.click(screen.getByRole('button',{name:'Reintentar consulta'}));
 await screen.findByText('No hay datasets que coincidan con la búsqueda.');
 expect(transport).toHaveBeenCalledTimes(2);
 expect(transport.mock.calls.every(call=>(call as unknown as [string,RequestInit])[1]?.method==='GET')).toBe(true);
});
it('preserves selection and keyboard navigation while searching the registered catalog without source labels',async()=>{
 const transport=vi.fn(async()=>Response.json({datasets:[
  {id:'Smoke',name:'Smoke',record_id:'legacy:7',source_type:'legacy',audio_count:9,class_count:3,eligible:true,eligibility_state:'current_flow_compatible',reasons:[]},
  {id:'MaquinariaMinas',name:'MaquinariaMinas',record_id:'legacy:8',source_type:'legacy',audio_count:0,class_count:null,eligible:false,eligibility_state:'blocked',reasons:['incompatible_configuration']},
 ]}));vi.stubGlobal('fetch',transport);
 const select=vi.fn();const view=render(<TrainingDatasetSelector onSelect={select}/>);
 expect(screen.queryByLabelText('Buscar dataset por nombre')).toBeNull();
 const trigger=screen.getByRole('combobox',{name:'Dataset para entrenamiento'});
 expect(trigger.textContent).toBe('Buscar o seleccionar dataset…');
 fireEvent.click(trigger);
 expect(screen.getByPlaceholderText('Buscar dataset por nombre…')).toBe(screen.getByLabelText('Buscar dataset por nombre'));
 const option=await screen.findByRole('option',{name:'Smoke'});
 expect(screen.getAllByRole('option')).toHaveLength(2);
 expect(screen.queryByText(/Privado|Compartido|legacy:7/)).toBeNull();
 fireEvent.mouseEnter(option);
 expect(screen.getByLabelText('Buscar dataset por nombre').getAttribute('aria-activedescendant')).toBe(option.id);
 expect(option.classList.contains('bg-[#23252e]')).toBe(true);
 expect(select).not.toHaveBeenCalled();
 fireEvent.click(option);
 expect(select).toHaveBeenLastCalledWith(expect.objectContaining({record_id:'legacy:7'}));
 fireEvent.keyDown(trigger,{key:'ArrowDown'});
 const search=screen.getByLabelText('Buscar dataset por nombre');
 expect(document.activeElement).toBe(search);
 fireEvent.change(search,{target:{value:'mAqUiNaRiA'}});
 expect(screen.getAllByRole('option',{name:'MaquinariaMinas'})).toHaveLength(1);
 fireEvent.keyDown(search,{key:'Escape'});
 expect(trigger.textContent).toBe('Smoke');
 expect(document.activeElement).toBe(trigger);
 expect(select).toHaveBeenCalledTimes(1);
 fireEvent.click(trigger);
 const keyboardSearch=screen.getByLabelText('Buscar dataset por nombre');
 fireEvent.keyDown(keyboardSearch,{key:'ArrowDown'});
 fireEvent.keyDown(keyboardSearch,{key:'ArrowUp'});
 fireEvent.keyDown(keyboardSearch,{key:'Enter'});
 expect(trigger.textContent).toBe('Smoke');
 expect(select).toHaveBeenCalledTimes(2);
 fireEvent.click(trigger);
 fireEvent.blur(screen.getByLabelText('Buscar dataset por nombre'),{relatedTarget:null});
 expect(trigger.getAttribute('aria-expanded')).toBe('false');
 view.rerender(<TrainingDatasetSelector disabled onSelect={select}/>);
 expect((trigger as HTMLButtonElement).disabled).toBe(true);
 fireEvent.click(trigger);fireEvent.keyDown(trigger,{key:'ArrowDown'});
 expect(screen.queryByLabelText('Buscar dataset por nombre')).toBeNull();
 expect(select).toHaveBeenCalledTimes(2);
 expect(transport).toHaveBeenCalledTimes(1);
});
