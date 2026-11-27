import {
  ButtonKindType,
  IconOnlyType,
  IconType,
} from '@drv-ds/drv-design-system-ng';

export interface ButtonIconOnly {
  label: string;
  kind: ButtonKindType;
  iconOnly: IconOnlyType;
  iconType: IconType;
  disabled: boolean;
  title?: string;
  buttonClick(): void;
}
