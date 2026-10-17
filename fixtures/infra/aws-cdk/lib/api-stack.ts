// FIXTURE: invented. No real account.
import { Stack, StackProps, RemovalPolicy } from "aws-cdk-lib";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as iam from "aws-cdk-lib/aws-iam";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as rds from "aws-cdk-lib/aws-rds";
import { Construct } from "constructs";

export class ApiStack extends Stack {
  constructor(scope: Construct, id: string, props?: StackProps) {
    super(scope, id, props);
    new s3.Bucket(this, "Uploads", { publicReadAccess: true, blockPublicAccess: s3.BlockPublicAccess.BLOCK_ACLS, removalPolicy: RemovalPolicy.DESTROY, autoDeleteObjects: true });
    const role = new iam.Role(this, "Worker", { assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com") });
    role.addToPolicy(new iam.PolicyStatement({ actions: ["s3:*"], resources: ["*"] }));
    const vpc = new ec2.Vpc(this, "Vpc", { natGateways: 3 });
    const sg = new ec2.SecurityGroup(this, "Db", { vpc });
    sg.addIngressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(5432));
    new rds.DatabaseInstance(this, "Orders2", { engine: rds.DatabaseInstanceEngine.POSTGRES, vpc, securityGroups: [sg], publiclyAccessible: true, storageEncrypted: false, deletionProtection: false });
  }
}
