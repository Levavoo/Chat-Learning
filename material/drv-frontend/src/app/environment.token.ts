import { InjectionToken } from '@angular/core';
import { EnvironmentConfig } from 'src/environments/environment-config';

export const ENV_CONFIG = new InjectionToken<EnvironmentConfig>('ENV_CONFIG');
