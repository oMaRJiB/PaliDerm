"""Developer-only deterministic contract fixture. Never imported by app startup."""
from backend.ai.adapter import AnalysisOutput, Candidate


class FixtureAdapter:
    model_name = 'SIMULATED AI — not model inference'
    model_version = 'fixture-1'
    prompt_version = 'not-applicable'

    def analyze_case(self, input):
        return AnalysisOutput(self.model_name,self.model_version,self.prompt_version,'undetermined',
                              'SIMULATED AI — not model inference','Deterministic software test only',
                              'No clinical model was invoked; no clinical meaning.',
                              (Candidate('Synthetic fixture label',1,None,'Test data only'),),
                              {image.image_id:'poor' for lesion in input.lesions for image in lesion.images})
