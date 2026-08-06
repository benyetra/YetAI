import {
  DraftBoard,
  ManagersMark,
  MovesMark,
  RecordBook,
  RivalryMark,
  StadiumMark,
  TrophyCup,
} from './illustrations';

export type VaultExploreIconName =
  | 'trophy'
  | 'records'
  | 'managers'
  | 'seasons'
  | 'h2h'
  | 'moves'
  | 'draft';

const CLASS = 'vault-illust vault-explore-illust';

export function VaultExploreIcon({ name }: { name: VaultExploreIconName }) {
  switch (name) {
    case 'trophy':
      return <TrophyCup className={CLASS} />;
    case 'records':
      return <RecordBook className={CLASS} />;
    case 'managers':
      return <ManagersMark className={CLASS} />;
    case 'seasons':
      return <StadiumMark className={CLASS} />;
    case 'h2h':
      return <RivalryMark className={CLASS} />;
    case 'moves':
      return <MovesMark className={CLASS} />;
    case 'draft':
      return <DraftBoard className={CLASS} />;
    default:
      return null;
  }
}
