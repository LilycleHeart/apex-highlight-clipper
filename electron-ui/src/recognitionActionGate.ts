/** Click guard only; durable idempotency belongs to the backend task store. */
export class RecognitionActionGate {
 private identity:string;private token:symbol|null=null;
 constructor(identity:string){this.identity=identity;}
 update(identity:string){if(identity===this.identity)return false;this.identity=identity;this.token=null;return true;}
 begin(){if(this.token)return null;this.token=Symbol(this.identity);return this.token;}
 fail(token:symbol){if(this.token!==token)return false;this.token=null;return true;}
 get pending(){return this.token!==null;}
}
