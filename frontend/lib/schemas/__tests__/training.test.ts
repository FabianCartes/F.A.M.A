import { expect, it } from 'vitest';
import { TrainingDatasetSchema, TrainingCatalogDatasetSchema } from '../training';

it('keeps the default dataset contract separate from the opt-in unknown metadata projection',()=>{
 expect(TrainingDatasetSchema.parse({id:'default',name:'Default',audio_count:0}).class_count).toBe(15);
 const row={id:'other',name:'Other',audio_count:0,source_type:'legacy',record_id:'legacy:4',class_count:null,eligible:false,eligibility_state:'blocked',reasons:['incompatible_configuration']};
 expect(TrainingCatalogDatasetSchema.parse(row).class_count).toBeNull();
 expect(TrainingDatasetSchema.safeParse(row).success).toBe(false);
 expect(TrainingCatalogDatasetSchema.safeParse({...row,source_type:'imported'}).success).toBe(false);
 expect(TrainingCatalogDatasetSchema.safeParse({...row,eligibility_state:'ready'}).success).toBe(false);
});
