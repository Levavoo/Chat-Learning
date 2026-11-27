export const FEEDBACK_RATING_VALUES = {
  testingType: {
    options: [
      {
        title: 'Fachlicher Test (Single-Turn)',
        value: 'singleturn',
        description:
          'Ziel des Tests: Bewertet wird die fachliche Qualität von Renates erster Antwort auf eine Nutzerfrage. Wenn Renate zuerst eine Verständnis-Rückfrage stellt, darf diese beantwortet werden und danach die Antwort darauf bewertet werden.',
        nottice:
          'Hinweis: Bitte bewerten Sie einmal jede Antwort, die gegeben wurde. Für eine neue Frage, starten Sie bitte ein neues Gespräch (über den Button „Neues Gespräch“).',
      },
      {
        title: 'Dialogtest (Multi-Turn)',
        value: 'multiturn',
        description:
          'Bewertet wird die Fähigkeit, eine zusammenhängende Diskussion mit guter Antwortqualität in den unterschiedlichen Szenarien zu führen.',
        nottice:
          'Bitte bewerten Sie einmal für die gesamte Konversation, nicht einzelne Antworten.',
      },
      {
        title: 'Finales Feedback',
        value: 'finalFeedback',
        description:
          'Hinweis: Bitte geben Sie einmalig eine finale Bewertung für Renate mit ihrer persönlichen Meinung am Ende des Tests ab.',
      },
    ],
  },
  perTurnTestDescription: {
    title: 'Bewertung pro Turn (Multi-Turn)',
    value: 'multiturn',
    description: 'Bewertet wird die fachliche Korrektheit dieser Antwort.',
    nottice: 'Bitte bewerten Sie jede Antwort einzeln.',
  },
  singleTurn: {
    technicalCorrectivity: {
      question: 'Fachliche Korrektheit: Ist der Antworttext fachlich korrekt?',
      options: [
        {
          title: 'Ja',
          value: 'Yes',
        },
        {
          title: 'Eher Ja',
          value: 'Likely yes',
        },
        {
          title: 'Eher Nein',
          value: 'Probably not',
        },
        {
          title: 'Nein',
          value: 'No',
        },
        {
          title: 'Kann ich nicht bewerten (z.B. bei Fehlermeldung)',
          value: 'Cannot evaluate',
        },
      ],
    },
    coverageLevel: {
      question: 'Abdeckung: Deckt die Antwort die wesentlichen Punkte ab?',
      options: [
        {
          title: 'Ja',
          value: 'Yes',
        },
        {
          title: 'Eher Ja',
          value: 'Likely yes',
        },
        {
          title: 'Eher Nein',
          value: 'Probably not',
        },
        {
          title: 'Nein',
          value: 'No',
        },
        {
          title: 'Kann ich nicht bewerten (z.B. bei Fehlermeldung)',
          value: 'Cannot evaluate',
        },
      ],
    },
    tonality: {
      question:
        'Tonalität: Passen Ton und Ansprache zur Zielgruppe und Fragestellung?',
      options: [
        {
          title: 'Ja',
          value: 'Yes',
        },
        {
          title: 'Eher Ja',
          value: 'Likely yes',
        },
        {
          title: 'Eher Nein',
          value: 'Probably not',
        },
        {
          title: 'Nein',
          value: 'No',
        },
        {
          title: 'Kann ich nicht bewerten (z.B. bei Fehlermeldung)',
          value: 'Cannot evaluate',
        },
      ],
    },
    comprehensibility: {
      question:
        'Verständlichkeit: Ist die Antwort für Fachfremde verständlich formuliert? ',
      options: [
        {
          title: 'Ja',
          value: 'Yes',
        },
        {
          title: 'Eher Ja',
          value: 'Likely yes',
        },
        {
          title: 'Eher Nein',
          value: 'Probably not',
        },
        {
          title: 'Nein',
          value: 'No',
        },
        {
          title: 'Kann ich nicht bewerten (z.B. bei Fehlermeldung)',
          value: 'Cannot evaluate',
        },
      ],
    },
    precision: {
      question: 'Präzision: Trifft die Antwort exakt die gestellte Frage?',
      options: [
        {
          title: 'Ja',
          value: 'Yes',
        },
        {
          title: 'Eher Ja',
          value: 'Likely yes',
        },
        {
          title: 'Eher Nein',
          value: 'Probably not',
        },
        {
          title: 'Nein',
          value: 'No',
        },
        {
          title: 'Kann ich nicht bewerten (z.B. bei Fehlermeldung)',
          value: 'Cannot evaluate',
        },
      ],
    },
    sourceMatching: {
      question:
        'Quellenpassung: Werden die thematisch richtigen Dokumente zur Beantwortung der Frage herangezogen?',
      options: [
        {
          title: 'Ja',
          value: 'Yes',
        },
        {
          title: 'Eher Ja',
          value: 'Likely yes',
        },
        {
          title: 'Eher Nein',
          value: 'Probably not',
        },
        {
          title: 'Nein',
          value: 'No',
        },
        {
          title: 'Kann ich nicht bewerten (z.B. bei Fehlermeldung)',
          value: 'Cannot evaluate',
        },
      ],
    },
    sourceQuality: {
      question:
        'Quellenqualität: Enthalten die verwendeten Textabschnitte die relevanten Inhalte zur Frage?',
      options: [
        {
          title: 'Ja',
          value: 'Yes',
        },
        {
          title: 'Eher Ja',
          value: 'Likely yes',
        },
        {
          title: 'Eher Nein',
          value: 'Probably not',
        },
        {
          title: 'Nein',
          value: 'No',
        },
        {
          title: 'Kann ich nicht bewerten (z.B. bei Fehlermeldung)',
          value: 'Cannot evaluate',
        },
      ],
    },
    comparabilityToGoogleAi: {
      question:
        'Vergleichbarkeit zur Google-KI: Wie schätzen Sie die fachliche Korrektheit von Renate im Vergleich zur Google-KI ein?',
      options: [
        {
          title: 'Besser',
          value: 'Better',
        },
        {
          title: 'Gleich Gut',
          value: 'Equally good',
        },
        {
          title: 'Gleich Schlecht',
          value: 'Equally bad',
        },
        {
          title: 'Schlechter',
          value: 'Worse',
        },
        {
          title: 'Kann ich nicht bewerten (z.B. bei Fehlermeldung)',
          value: 'Cannot evaluate',
        },
      ],
    },
  },
  multiturn: {
    usedScenario: {
      question: 'Welches Szenario wurde verwendet?',
      options: [
        { title: '1', value: 1 },
        { title: '2', value: 2 },
        { title: '3', value: 3 },
        { title: '4', value: 4 },
        { title: '5', value: 5 },
        { title: '6', value: 6 },
        { title: 'Freie Vertestung', value: 0 },
      ],
    },
    technicalCorrectivity: {
      question: 'Fachliche Korrektheit: Ist der Antworttext fachlich korrekt?',
      options: [
        {
          title: 'Ja',
          value: 'Yes',
        },
        {
          title: 'Eher Ja',
          value: 'Likely yes',
        },
        {
          title: 'Eher Nein',
          value: 'Probably not',
        },
        {
          title: 'Nein',
          value: 'No',
        },
        {
          title: 'Kann ich nicht bewerten (z.B. bei Fehlermeldung)',
          value: 'Cannot evaluate',
        },
      ],
    },
    dialogueSkills: {
      question:
        'Dialogfähigkeit: Reagiert Renate in Form eines Gesprächs auf Rückfragen und den vorherigen Gesprächsverlauf?',
      options: [
        {
          title: 'Ja',
          value: 'Yes',
        },
        {
          title: 'Eher Ja',
          value: 'Likely yes',
        },
        {
          title: 'Eher Nein',
          value: 'Probably not',
        },
        {
          title: 'Nein',
          value: 'No',
        },
        {
          title: 'Kann ich nicht bewerten (z.B. bei Fehlermeldung)',
          value: 'Cannot evaluate',
        },
      ],
    },
    goalAchievement: {
      question:
        'Zielerreichung: Wurde das Gespräch insgesamt sinnvoll zum Ziel geführt? ',
      options: [
        {
          title: 'Ja',
          value: 'Yes',
        },
        {
          title: 'Eher Ja',
          value: 'Likely yes',
        },
        {
          title: 'Eher Nein',
          value: 'Probably not',
        },
        {
          title: 'Nein',
          value: 'No',
        },
        {
          title: 'Kann ich nicht bewerten (z.B. bei Fehlermeldung)',
          value: 'Cannot evaluate',
        },
      ],
    },
    handlingCorrections: {
      question:
        'Umgang mit Korrektur: Geht Renate sinnvoll mit Korrekturen oder Widerspruch durch den Nutzer um? (Wenn das im Gespräch vorkam) (optional)',
      options: [
        {
          title: 'Ja',
          value: 'Yes',
        },
        {
          title: 'Eher Ja',
          value: 'Likely yes',
        },
        {
          title: 'Eher Nein',
          value: 'Probably not',
        },
        {
          title: 'Nein',
          value: 'No',
        },
        {
          title: 'Kann ich nicht bewerten (z.B. bei Fehlermeldung)',
          value: 'Cannot evaluate',
        },
      ],
    },
  },
  finalFeedback: {
    goodToRecommend: {
      question: 'Hat Renate zum jetzigen Stand einen Mehrwert für Nutzende?',
      options: [
        {
          title: 'Ja',
          value: 'Yes',
        },
        {
          title: 'Eher Ja',
          value: 'Likely yes',
        },
        {
          title: 'Eher Nein',
          value: 'Probably not',
        },
        {
          title: 'Nein',
          value: 'No',
        },
        {
          title: 'Kann ich nicht bewerten (z.B. bei Fehlermeldung)',
          value: 'Cannot evaluate',
        },
      ],
    },
  },
};
