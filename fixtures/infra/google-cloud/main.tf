# FIXTURE: invented. No real project.
provider "google" { project = "shop-prod-fixture" }

resource "google_storage_bucket" "exports" {
  name          = "shop-exports-fixture"
  location      = "EU"
  force_destroy = true
  public_access_prevention = "inherited"
}
resource "google_storage_bucket_iam_member" "public_read" {
  bucket = google_storage_bucket.exports.name
  role   = "roles/storage.objectViewer"
  member = "allUsers"
}
resource "google_project_iam_member" "ci" {
  project = "shop-prod-fixture"
  role    = "roles/owner"
  member  = "serviceAccount:ci@shop-prod.example.com"
}
resource "google_cloud_run_service_iam_member" "open" {
  service = "shop-api"
  role    = "roles/run.invoker"
  member  = "allUsers"
}
resource "google_sql_database_instance" "main" {
  name             = "shop-db-v2"
  database_version = "POSTGRES_15"
  deletion_protection = false
}
