/** L4's section review contract (v2 spec §9.2), under the names this feature uses. */
import type {
  Colleague,
  CoverageMark,
  Decision,
  MentorPrompt,
  RubricLine,
  SectionReview,
  SectionReviewPage,
  StepId,
} from '../../aipm/types';

export type { Decision, MentorPrompt, RubricLine, SectionReview, SectionReviewPage, StepId };
export type ReviewStatus = SectionReview['status'];
/** The review's colleague key: `tech` where the result page says `technical`. */
export type ReviewColleague = Colleague;
export type CoverageItem = CoverageMark;
