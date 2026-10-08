// Provider-specific optional fields remain in Row until their contracts are narrowed.
export type Row = Record<string, any>;
export type RainStation = {
  station_id: string;
  name: string;
  latitude: number;
  longitude: number;
  rainfall_mm: number | null;
  quality_status: string;
  groundwater_station_id?: string | null;
  model_ready?: boolean;
  region_name?: string;
};
export type GroundStation = {
  station_id: string;
  name: string;
  region_code: string;
  district_name?: string;
  latitude: number;
  longitude: number;
  verified: boolean;
  level_unit: string;
  level_reference: string;
  blockers: string[];
  evidence: string[];
  source_layer_quality?: string;
};
