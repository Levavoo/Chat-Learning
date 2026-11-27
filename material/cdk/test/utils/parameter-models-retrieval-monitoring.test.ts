import * as cdk from 'aws-cdk-lib';
import { getETLParameters } from '../../lib/utils/parameter-models';

const minEtlRequired = {
  envName: 'prod',
  account: '718036735727',
  etlStackName: 'renate-etl-kb-prod',
};

function makeApp(context: Record<string, unknown> = {}): cdk.App {
  return new cdk.App({ context });
}

describe('getETLParameters — retrieval alarm action gate (#671)', () => {
  test('defaults to false so prod official notifications cannot activate early', () => {
    const params = getETLParameters(
      makeApp(),
      'prod',
      new Map([['prod', minEtlRequired]]),
    );
    expect(params.retrievalHealthAlarmActionsEnabled).toBe(false);
  });

  test('config.yaml override enables actions after supervised health verification', () => {
    const params = getETLParameters(
      makeApp(),
      'prod',
      new Map([['prod', minEtlRequired]]),
      { retrievalHealthAlarmActionsEnabled: true },
    );
    expect(params.retrievalHealthAlarmActionsEnabled).toBe(true);
  });

  test('rejects a non-boolean config override', () => {
    expect(() =>
      getETLParameters(makeApp(), 'prod', new Map([['prod', minEtlRequired]]), {
        retrievalHealthAlarmActionsEnabled: 'yes',
      }),
    ).toThrow(/Expected boolean context value/);
  });
});
