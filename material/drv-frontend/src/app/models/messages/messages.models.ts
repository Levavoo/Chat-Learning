import { LocalNotification } from '@components/feedback/feedback.component';
import {
  ExampleQuestionCategory,
  ExampleQuestionLinklistData,
} from './exampleQuestionLinklistData';

export const ASSISTANT_NAME_PREFIX = '<strong>Renate:</strong> ';

export const FALLBACK_ERROR_STATUSES = [0, 502, 503, 504];

export const exampleQuestions: ExampleQuestionLinklistData[] = [
  {
    text: 'Wann kann ich in Rente gehen und wie hoch ist meine Rente?',
    icon: 'document',
    disabled: false,
    category: ExampleQuestionCategory.Rente,
    faqUrl:
      'https://www.deutsche-rentenversicherung.de/SharedDocs/FAQ/A-und-B/faq-a-und-b.html?nn=d9301a88-c67c-4230-ae1f-acd2973b0e2d#',
    answerUrl:
      'https://www.deutsche-rentenversicherung.de/DRV/DE/Rente/Kurz-vor-der-Rente/Wann-kann-ich-in-Rente-gehen/wann-kann-ich-in-rente-gehen_node.html',
    additionalInfos:
      'https://www.deutsche-rentenversicherung.de/DRV/DE/Rente/Allgemeine-Informationen/Wissenswertes-zur-Rente/FAQs/Rente/Rentenbeginn/Rentenbeginn_Liste.html',
  },
  {
    text: 'Kann ich zusätzlich Geld in die Rentenversicherung einzahlen?',
    icon: 'document',
    disabled: false,
    category: ExampleQuestionCategory.Rente,
    faqUrl:
      'https://www.deutsche-rentenversicherung.de/SharedDocs/FAQ/A-und-B/faq-a-und-b.html?nn=d9301a88-c67c-4230-ae1f-acd2973b0e2d#',
    additionalInfos:
      'https://www.deutsche-rentenversicherung.de/DRV/DE/Rente/Allgemeine-Informationen/Wissenswertes-zur-Rente/FAQs/Rente/Rentenabschlaege/Rentenabschlag_Liste.html',
  },
  {
    text: 'Wie beantrage ich meine Rente?',
    icon: 'document',
    disabled: false,
    category: ExampleQuestionCategory.Rente,
    faqUrl:
      'https://www.deutsche-rentenversicherung.de/SharedDocs/FAQ/A-und-B/faq-a-und-b.html?nn=d9301a88-c67c-4230-ae1f-acd2973b0e2d#',
    answerUrl:
      'https://www.deutsche-rentenversicherung.de/DRV/DE/Rente/Kurz-vor-der-Rente/Wie-beantrage-ich-meine-Rente/Wie-beantrage-ich-meine-Rente_detailseite.html',
  },
  {
    text: 'Wer kann mir bei Fragen zu einem Antrag weiterhelfen?',
    icon: 'document',
    disabled: false,
    category: ExampleQuestionCategory.Rente,
    faqUrl:
      'https://www.deutsche-rentenversicherung.de/SharedDocs/FAQ/A-und-B/faq-a-und-b.html?nn=d9301a88-c67c-4230-ae1f-acd2973b0e2d#',
    additionalInfos:
      'https://eantrag.deutsche-rentenversicherung.de/ea-eantrag-nx/formular/S8003',
  },
  {
    text: 'Ich habe meine Rentenzahlung nicht erhalten, wer kann mir helfen?',
    icon: 'document',
    disabled: false,
    category: ExampleQuestionCategory.Rente,
    faqUrl:
      'https://www.deutsche-rentenversicherung.de/SharedDocs/FAQ/A-und-B/faq-a-und-b.html?nn=d9301a88-c67c-4230-ae1f-acd2973b0e2d#',
    additionalInfos:
      'https://www.deutschepost.de/de/r/rentenservice/gesetzliche-rente/FAQ.html',
  },
  {
    text: 'Wird mein Einkommen auf meine Rente angerechnet?',
    icon: 'document',
    disabled: false,
    category: ExampleQuestionCategory.Rente,
    faqUrl:
      'https://www.deutsche-rentenversicherung.de/SharedDocs/FAQ/A-und-B/faq-a-und-b.html?nn=d9301a88-c67c-4230-ae1f-acd2973b0e2d#',
    additionalInfos:
      'https://www.deutsche-rentenversicherung.de/SharedDocs/Downloads/DE/Broschueren/national/hinterbliebenenrente_hilfe_in_schweren_zeiten.html',
  },
  {
    text: 'Welche Auswirkungen hat es auf meine Rente, wenn ich im Ausland arbeite?',
    icon: 'document',
    disabled: false,
    category: ExampleQuestionCategory.Rente,
    faqUrl:
      'https://www.deutsche-rentenversicherung.de/SharedDocs/FAQ/A-und-B/faq-a-und-b.html?nn=d9301a88-c67c-4230-ae1f-acd2973b0e2d#',
  },
  {
    text: 'Bekomme ich meine Rente auch ins Ausland?',
    icon: 'document',
    disabled: false,
    category: ExampleQuestionCategory.Rente,
    faqUrl:
      'https://www.deutsche-rentenversicherung.de/SharedDocs/FAQ/A-und-B/faq-a-und-b.html?nn=d9301a88-c67c-4230-ae1f-acd2973b0e2d#',
    answerUrl:
      'https://www.deutsche-rentenversicherung.de/DRV/DE/Rente/Ausland/Rente-im-Ausland/rente-im-ausland-umzug-detailseite.html',
  },
  {
    text: 'Wie bekomme ich den Zuschlag für meine EM-Rente',
    icon: 'document',
    disabled: false,
    category: ExampleQuestionCategory.Rente,
    answerUrl:
      'https://www.deutsche-rentenversicherung.de/DRV/DE/Rente/Allgemeine-Informationen/EM-Rente-Verbesserung/em-verbesserungsgesetz_node.html',
  },
  {
    text: 'Was passiert mit meinen Beiträgen, wenn ich ins Ausland ziehe?',
    icon: 'document',
    disabled: false,
    category: ExampleQuestionCategory.Versicherung,
    faqUrl:
      'https://www.deutsche-rentenversicherung.de/SharedDocs/FAQ/A-und-B/faq-a-und-b.html?nn=d9301a88-c67c-4230-ae1f-acd2973b0e2d#',
    answerUrl:
      'https://www.deutsche-rentenversicherung.de/DRV/DE/Rente/Ausland/ausland_node.html',
  },
  {
    text: 'Muss ich mich bei der Rentenversicherung melden, wenn ich zeitweise im Ausland arbeiten muss?',
    icon: 'document',
    disabled: false,
    category: ExampleQuestionCategory.Versicherung,
    faqUrl:
      'https://www.deutsche-rentenversicherung.de/SharedDocs/FAQ/A-und-B/faq-a-und-b.html?nn=d9301a88-c67c-4230-ae1f-acd2973b0e2d#',
    answerUrl:
      'https://www.deutsche-rentenversicherung.de/DRV/DE/Rente/Ausland/ausland_node.html',
  },
  {
    text: 'Muss ich als selbstständige Person Beiträge zahlen?',
    icon: 'document',
    disabled: false,
    category: ExampleQuestionCategory.Versicherung,
    faqUrl:
      'https://www.deutsche-rentenversicherung.de/SharedDocs/FAQ/A-und-B/faq-a-und-b.html?nn=d9301a88-c67c-4230-ae1f-acd2973b0e2d#',
    answerUrl:
      'https://www.deutsche-rentenversicherung.de/DRV/DE/Rente/Arbeitnehmer-und-Selbststaendige/03_Selbststaendige/selbststaendige_Inhalt.html',
    additionalInfos:
      ' https://www.deutsche-rentenversicherung.de/SharedDocs/Formulare/DE/_pdf/V0020.html',
  },
  {
    text: 'Bekomme ich auch Mütterrente?',
    icon: 'document',
    disabled: false,
    category: ExampleQuestionCategory.Versicherung,
    answerUrl:
      'https://www.deutsche-rentenversicherung.de/SiteGlobals/Forms/Suche/DE/DRV/Servicesuche_Formular.html?nn=75344bbe-ab71-4da6-9bdc-244162aa5440&resourceId=eb47fad2-27ce-4ae2-afad-f6fa946af677&input_=75344bbe-ab71-4da6-9bdc-244162aa5440&pageLocale=de&templateQueryString=M%C3%BCtterrente&submit=#',
  },
  {
    text: 'Ich bin krank, kann mir die Rentenversicherung helfen?',
    icon: 'document',
    disabled: false,
    category: ExampleQuestionCategory.Reha,
    faqUrl:
      'https://www.deutsche-rentenversicherung.de/SharedDocs/FAQ/A-und-B/faq-a-und-b.html?nn=d9301a88-c67c-4230-ae1f-acd2973b0e2d#',
    answerUrl:
      'https://www.deutsche-rentenversicherung.de/DRV/DE/Reha/Warum-Reha/warum-reha_node.html',
  },
  {
    text: 'Kann ich mir bei einer Reha eine Klinik aussuchen?',
    icon: 'document',
    disabled: false,
    category: ExampleQuestionCategory.Reha,
    answerUrl:
      'https://www.deutsche-rentenversicherung.de/DRV/DE/Reha/wunsch-und-wahlrecht/wunsch-und-wahlrecht-node.html',
  },
  {
    text: 'Was ist eine berufliche Reha?',
    icon: 'document',
    disabled: false,
    category: ExampleQuestionCategory.Reha,
    answerUrl:
      'https://www.deutsche-rentenversicherung.de/DRV/DE/Reha/Berufliche-Reha/berufliche-reha_node.html',
  },
  {
    text: 'Gibt es eine Reha für Kinder?',
    icon: 'document',
    disabled: false,
    category: ExampleQuestionCategory.Reha,
    answerUrl:
      'https://www.deutsche-rentenversicherung.de/DRV/DE/Reha/Medizinische-Reha/Reha-fuer-Kinder-und-Jugendliche/reha-fuer-kinder-und-jugendliche_node.html',
  },
  {
    text: 'Wie geht es nach meiner Reha weiter?',
    icon: 'document',
    disabled: false,
    category: ExampleQuestionCategory.Reha,
    answerUrl:
      'https://www.deutsche-rentenversicherung.de/DRV/DE/Reha/Reha-Nachsorge/reha-nachsorge_node.html',
  },
  {
    text: 'Wo kann ich mich beraten lassen?',
    icon: 'document',
    disabled: false,
    category: ExampleQuestionCategory.Sonstiges,
    faqUrl:
      'https://www.deutsche-rentenversicherung.de/SharedDocs/FAQ/A-und-B/faq-a-und-b.html?nn=6f140aab-14de-482f-a0bd-767b64ac9947#d257aca8-1368-43b4-b2c7-f7f451029557',
    additionalInfos:
      'https://www.deutsche-rentenversicherung.de/DRV/DE/Beratung-und-Kontakt/Beratung-suchen-und-buchen/beratung-suchen-und-buchen_node.html',
  },
  {
    text: 'Muss ich als Rentnerin oder Rentner Beiträge zur Krankenversicherung zahlen?',
    icon: 'document',
    disabled: false,
    category: ExampleQuestionCategory.Sonstiges,
    additionalInfos:
      'https://www.deutsche-rentenversicherung.de/SharedDocs/Glossareintraege/DE/K/kvdr.html',
  },
  {
    text: 'Wie bekomme ich eine Rentenauskunft oder Renteninformation?',
    icon: 'document',
    disabled: false,
    category: ExampleQuestionCategory.Sonstiges,
    faqUrl:
      'https://www.deutsche-rentenversicherung.de/SharedDocs/FAQ/A-und-B/faq-a-und-b.html?nn=d9301a88-c67c-4230-ae1f-acd2973b0e2d#',
    additionalInfos:
      'https://www.deutsche-rentenversicherung.de/DRV/DE/Online-Services/online-services_node.html',
  },
  {
    text: 'Wie kann ich persönliche Daten ändern?',
    icon: 'document',
    disabled: false,
    category: ExampleQuestionCategory.Sonstiges,
    faqUrl:
      'https://www.deutsche-rentenversicherung.de/SharedDocs/FAQ/A-und-B/faq-a-und-b.html?nn=d9301a88-c67c-4230-ae1f-acd2973b0e2d#',
    additionalInfos:
      'https://www.deutsche-rentenversicherung.de/DRV/DE/Online-Services/online-services_node.html',
  },
  {
    text: 'Muss ich auf meine Rente Steuern zahlen?',
    icon: 'document',
    disabled: false,
    category: ExampleQuestionCategory.Sonstiges,
    answerUrl:
      'https://www.deutsche-rentenversicherung.de/DRV/DE/Rente/Allgemeine-Informationen/Besteuerung-der-Rente/Besteuerung_der_Rente.html',
    additionalInfos: 'https://www.eservice-drv.de/SelfServiceWeb/',
  },
];

const urlBros =
  'https://www.deutsche-rentenversicherung.de/DRV/DE/Ueber-uns-und-Presse/Mediathek/Broschueren/broschueren_node.html';
const urlDataProtect =
  'https://www.deutsche-rentenversicherung.de/DRV/DE/Service/Footer/Datenschutz/datenschutz_node.html';

export const welcomeMessage = `
<strong>Renate:</strong> Hallo, ich bin Renate – Der Rentenchat, Ihr KI-Chatbot der Deutschen Rentenversicherung. <br>
Mein Wissen basiert auf der <a href="${urlBros}" rel="noopener noreferrer" target="_blank">Gemeinsamen Broschürenreihe der Deutschen Rentenversicherung</a>.
Fragen Sie mich gern alles rund um Rente, Reha oder Prävention.
Bitte teilen Sie <a href="${urlDataProtect}" target="_blank" rel="noopener noreferrer">keine personenbezogenen Daten</a> mit mir. <br>
Wichtig: Aktuell sehen Sie hier eine Beta-Version, Hinweise auf Fehler und ungenaue Antworten helfen mir, mich weiterzuentwickeln.`;

export const feedbackNotificationId = 'feedbackNotificationId';
export const chatNotificationId = 'chatNotificationId';

export const feedbackSuccessNotification: LocalNotification = {
  notificationId: chatNotificationId,
  id: chatNotificationId,
  variant: 'success',
  title: 'Feedback erfolgreich versendet',
  duration: 3,
};

export const feedbackErrorNotification: LocalNotification = {
  notificationId: feedbackNotificationId,
  id: chatNotificationId,
  variant: 'alert',
  title: 'Ihr Feedback konnte nicht gesendet werden.',
  duration: 3,
};

export const chatErrorNotification: LocalNotification = {
  notificationId: chatNotificationId,
  id: chatNotificationId,
  variant: 'alert',
  title: 'Es ist ein Fehler aufgetreten',
  text: 'Die Anfrage konnte nicht verarbeitet werden. Bitte versuchen Sie es zu einem späteren Zeitpunkt erneut!',
};

export const chatServiceUnavailableNotification: LocalNotification = {
  notificationId: chatNotificationId,
  id: chatNotificationId,
  variant: 'alert',
  title: 'Dienst nicht verfügbar',
  text: 'Der Chat-Dienst ist derzeit ausgelastet oder vorübergehend nicht verfügbar. Bitte versuchen Sie es später erneut.',
};

export const chatTechnicalErrorNotification: LocalNotification = {
  notificationId: chatNotificationId,
  id: chatNotificationId,
  variant: 'alert',
  title: 'Es ist ein Fehler aufgetreten',
  text: 'Es ist ein technischer Fehler aufgetreten. Bitte versuchen Sie es zu einem späteren Zeitpunkt erneut!',
};

export const chatTimeoutNotification: LocalNotification = {
  notificationId: chatNotificationId,
  id: chatNotificationId,
  variant: 'alert',
  title: 'Zeitüberschreitung',
  text: 'Die Verarbeitung dauert gerade etwas länger. Bitte versuchen Sie es erneut.',
};

export const chatNetworkErrorNotification: LocalNotification = {
  notificationId: chatNotificationId,
  id: chatNotificationId,
  variant: 'alert',
  title: 'Netzwerkfehler',
  text: 'Netzwerkfehler. Bitte prüfen Sie Ihre Internetverbindung.',
};

export const applicationStateErrorNotification: LocalNotification = {
  notificationId: chatNotificationId,
  id: chatNotificationId,
  variant: 'alert',
  title: 'Anwendungsfehler',
  text: 'Die Anwendung muss neu geladen werden. Bitte laden Sie die Seite neu.',
};

export const chatBlockedNotification: LocalNotification = {
  notificationId: chatNotificationId,
  id: chatNotificationId,
  variant: 'alert',
  title: 'Anfrage blockiert',
  text: 'Ihre Anfrage wurde aus Sicherheitsgründen blockiert. Bitte versuchen Sie es erneut.',
};

export const chatRateLimitNotification: LocalNotification = {
  notificationId: chatNotificationId,
  id: chatNotificationId,
  variant: 'alert',
  title: 'Zu viele Anfragen',
  text: 'Zu viele Anfragen. Bitte versuchen Sie es in einigen Minuten erneut.',
};

export const chatConversationLimitNotification: LocalNotification = {
  notificationId: chatNotificationId,
  id: chatNotificationId,
  variant: 'alert',
  title: 'Konversation zu lang',
  text: 'Diese Konversation ist zu lang. Bitte beginnen Sie über den Button „Neues Gespräch“ eine neue Konversation.',
};

export const copyConversationIdSuccessNotification: LocalNotification = {
  notificationId: chatNotificationId,
  id: chatNotificationId,
  variant: 'success',
  title: 'ConversationId in Zwischenablage kopiert.',
  duration: 3,
};

export const sessionDataDeleteSuccessful: LocalNotification = {
  notificationId: chatNotificationId,
  id: chatNotificationId,
  variant: 'success',
  title:
    'Die Einwilligung wurde widerrufen und alle Eingaben dieser Sitzung wurden erfolgreich gelöscht.',
  duration: 3,
};
