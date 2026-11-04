import type { SceneKind } from "../types";
import { AfterScene } from "./AfterScene";
import { BeforeScene } from "./BeforeScene";
import { ClosingScene } from "./ClosingScene";
import { ColdOpenScene } from "./ColdOpenScene";
import { FootageScene } from "./FootageScene";
import { HookDemoScene } from "./HookDemoScene";
import { MaskingScene } from "./MaskingScene";
import { PipelineScene } from "./PipelineScene";
import { ProblemScene } from "./ProblemScene";
import { PromisesScene } from "./PromisesScene";
import { ReportScene } from "./ReportScene";
import { TitleScene } from "./TitleScene";
import type { SceneComponentProps } from "./types";

export const SCENE_COMPONENTS: Record<
  SceneKind,
  React.FC<SceneComponentProps>
> = {
  title: TitleScene,
  coldopen: ColdOpenScene,
  problem: ProblemScene,
  before: BeforeScene,
  after: AfterScene,
  footage: FootageScene,
  pipeline: PipelineScene,
  masking: MaskingScene,
  hookdemo: HookDemoScene,
  report: ReportScene,
  promises: PromisesScene,
  closing: ClosingScene,
};

export type { SceneComponentProps };
