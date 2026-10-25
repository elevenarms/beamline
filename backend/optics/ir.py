"""Design IR, trace result, and verify report schemas — the contract shared by
the tracer, verifier, agents, server and web viewer. Change only with care.

Conventions
- Units: millimetres, degrees, nanometres, milliwatts, MHz.
- Table frame: origin at the baseplate's lower-left corner, +x right, +y up,
  all optics in the z = 0 optical plane. Angles are CCW from +x.
- Polarization: Jones vector (Ex, Ey) in the beam's local frame, where
  x = "H" (in the table plane, p-polarized at a fold) and y = "V" (vertical, s).
- Branch names: every source starts a branch named by its id ("L1"). A beam that
  splits gets a suffix per output: beamsplitter/pbs/dichroic/sampler -> ".t"
  (transmitted) and ".r" (reflected); aom -> ".0" and ".+1" (or ".-1").
  Mirrors, lenses, waveplates, cells, isolators and irises keep the name.
  Example: "L1.r.+1" = source L1, reflected at a splitter, AOM +1 order.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

# ─────────────────────────────── design IR ───────────────────────────────

ElementType = Literal[
    "mirror",             # full reflector
    "lens",               # thin spherical lens (focal_length_mm)
    "half_wave_plate",    # fast_axis_deg
    "quarter_wave_plate", # fast_axis_deg
    "pbs",                # polarizing beamsplitter cube: transmits H, reflects V
    "beamsplitter",       # non-polarizing; split_ratio = reflected fraction (default 0.5)
    "sampler",            # pickoff; split_ratio = reflected fraction (default 0.05)
    "dichroic",           # reflects wavelengths < cutoff_nm if reflect == "below", else above
    "aom",                # acousto-optic modulator; diffracts aom_efficiency into aom_order
    "iris",               # aperture; clips by aperture_mm
    "fiber_coupler",      # terminates beam; computes coupling efficiency into fiber mode
    "photodiode",         # terminates beam; reports power
    "beam_dump",          # terminates beam
    "vapor_cell",         # pass-through with transmission (e.g. Rb cell)
    "isolator",           # passes forward (along angle_deg) with transmission, blocks reverse
    # Nonlinear elements (power-dependent; the tracer iterates to a self-consistent solution):
    "soa",                # semiconductor optical amplifier: gain G = G0 / (1 + P_total/P_sat), shared by all
                          # beams through it -> cross-gain modulation (a strong control beam darkens a probe)
    "sfg_crystal",        # chi(2) sum-frequency / second-harmonic crystal: two beams overlapping in it generate a
                          # new beam at 1/lambda_out = 1/lambda_1 + 1/lambda_2 with P = eta * P1 * P2 (optical AND)
    "saturable_absorber", # transmission rises with intensity: T = T0 + (1 - T0) * P / (P + P_sat) (thresholder)
]

TERMINATING: set[str] = {"fiber_coupler", "photodiode", "beam_dump"}
SPLITTING: set[str] = {"pbs", "beamsplitter", "sampler", "dichroic"}

PolarizationSpec = Literal["H", "V", "D", "A", "R", "L"] | float  # float = linear, deg from H


class Baseplate(BaseModel):
    width_mm: float = 300.0
    height_mm: float = 150.0
    thickness_mm: float = 25.4
    optical_height_mm: float = 12.7  # beam height above plate top (3D rendering only)
    grid_mm: float = 25.4            # mounting-hole pitch (rendering + snapping)


class Source(BaseModel):
    id: str
    label: str = ""
    group: str | None = None         # subsystem/module this belongs to (e.g. "cooling_422"), for grouping in UI
    part_number: str | None = None
    position: tuple[float, float]
    direction_deg: float
    wavelength_nm: float
    power_mw: float = 10.0
    waist_mm: float = 0.5            # 1/e^2 intensity radius at the waist
    waist_offset_mm: float = 0.0     # waist location along the beam from the source (+ = downstream)
    polarization: PolarizationSpec = "H"
    enabled: bool = True             # input switch: a disabled source emits nothing (logic inputs, shutters)


class Element(BaseModel):
    id: str
    type: ElementType
    label: str = ""
    group: str | None = None         # subsystem/module this belongs to
    part_number: str | None = None

    # Placement: EITHER (beam + distance_mm) OR at.
    beam: str | None = None          # branch name this element sits on, e.g. "L1.r"
    distance_mm: float | None = None # from the previous interaction on that branch (or the source)
    at: tuple[float, float] | None = None  # absolute table position

    # Orientation. angle_deg = direction of the element's optical axis / surface normal.
    # Defaults: transmissive parts face the incoming beam; mirrors need out_direction_deg or angle_deg.
    angle_deg: float | None = None
    out_direction_deg: float | None = None  # mirrors only: desired outgoing beam direction

    # Type-specific parameters (all optional; defaults applied by the tracer).
    aperture_mm: float | None = None         # clear aperture diameter (default 12.7; fiber 6; iris 2)
    focal_length_mm: float | None = None     # lens; fiber_coupler collimation lens
    fast_axis_deg: float | None = None       # waveplates, measured from H toward V
    split_ratio: float | None = None         # beamsplitter/sampler reflected fraction
    cutoff_nm: float | None = None           # dichroic
    reflect: Literal["below", "above"] | None = None  # dichroic: which side of cutoff reflects
    aom_frequency_mhz: float | None = None   # default 80
    aom_efficiency: float | None = None      # default 0.8, fraction into aom_order
    aom_order: Literal[1, -1] | None = None  # default +1
    acoustic_velocity_m_s: float | None = None  # default 4200 (TeO2 longitudinal)
    fiber_mfd_um: float | None = None        # mode-field diameter (default 5.0)
    transmission: float | None = None        # vapor_cell / isolator (default 1.0 / 0.9); saturable_absorber T0
    saturation_power_mw: float | None = None # soa / saturable_absorber P_sat (defaults 5 / 10)
    small_signal_gain_db: float | None = None  # soa G0 (default 15 dB)
    nl_efficiency_per_w: float | None = None   # sfg_crystal eta in 1/W (default 2.0; P_out = eta*P1*P2)

    @model_validator(mode="after")
    def _placement(self) -> "Element":
        on_beam = self.beam is not None and self.distance_mm is not None
        if on_beam == (self.at is not None):
            raise ValueError(f"element {self.id}: give either (beam + distance_mm) or at, not both/neither")
        return self


class Target(BaseModel):
    """A goal the verifier checks, e.g. at least 5 mW delivered into fiber F1."""
    element_id: str
    kind: Literal["min_power_mw", "min_coupling", "polarization"]
    value: float | str  # number, or "H"/"V"/... for polarization


class Module(BaseModel):
    """A subsystem occupying a rectangular region of the table (large multi-module designs)."""
    id: str
    title: str = ""
    region: tuple[float, float, float, float]  # x, y, width, height in mm (table frame)
    description: str = ""


class Design(BaseModel):
    name: str
    description: str = ""
    modules: list[Module] = Field(default_factory=list)  # optional; elements/sources refer via .group
    baseplate: Baseplate = Field(default_factory=Baseplate)
    sources: list[Source]
    elements: list[Element] = Field(default_factory=list)  # placement order matters per branch
    targets: list[Target] = Field(default_factory=list)
    notes: str = ""


# ─────────────────────────────── trace result ────────────────────────────

class Segment(BaseModel):
    id: str
    branch: str
    source_id: str
    start: tuple[float, float]
    end: tuple[float, float]
    direction_deg: float
    length_mm: float
    wavelength_nm: float
    freq_shift_mhz: float = 0.0       # accumulated AOM shift
    power_mw: float
    jones: tuple[tuple[float, float], tuple[float, float]]  # ((Ex_re, Ex_im), (Ey_re, Ey_im)), normalized
    polarization_label: str           # "H", "V", "D", "A", "R", "L", "linear 30°", "elliptical"
    # Gaussian beam: w(z) = w0*sqrt(1+((z - waist_z_mm)/rayleigh_mm)^2), z measured from start.
    waist_z_mm: float
    rayleigh_mm: float
    w0_mm: float
    w_start_mm: float
    w_end_mm: float
    start_element: str | None = None  # element id or source id
    end_element: str | None = None
    end_reason: Literal["element", "escaped", "absorbed", "max_depth"] = "element"


class ElementHit(BaseModel):
    segment_id: str
    power_in_mw: float
    w_mm: float                       # beam radius at the element
    clip_loss: float                  # fraction of power outside the clear aperture
    offset_mm: float                  # beam centre distance from element centre


class PlacedElement(BaseModel):
    id: str
    type: ElementType
    placed: bool
    position: tuple[float, float] | None = None
    angle_deg: float | None = None
    hits: list[ElementHit] = Field(default_factory=list)
    coupling_efficiency: float | None = None  # fiber_coupler only (mode overlap x clipping)
    power_out_mw: float | None = None         # terminating elements: power absorbed/coupled
    error: str | None = None                  # why it could not be placed


class TraceResult(BaseModel):
    segments: list[Segment]
    elements: list[PlacedElement]
    branches: list[str]               # all branch names that exist after tracing


# ─────────────────────────────── verify report ───────────────────────────

class Check(BaseModel):
    id: str                           # e.g. "clipping", "stray_beam", "unplaced", "target", "collision", "off_table"
    severity: Literal["error", "warning", "info"]
    message: str
    element_id: str | None = None
    segment_id: str | None = None
    value: float | None = None
    limit: float | None = None


class VerifyReport(BaseModel):
    passed: bool                      # no errors and all targets met
    score: float                      # 0-100, for ranking candidate designs
    checks: list[Check]
    metrics: dict[str, float] = Field(default_factory=dict)  # input_mw, delivered_mw, stray_mw, n_elements, ...
