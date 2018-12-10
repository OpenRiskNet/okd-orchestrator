# -----------------------------------------------------------------------------
# Provider Data
# -----------------------------------------------------------------------------

# Bastion and Cluster AMIs
# Extracted from AWS using the aws_ami data

data "aws_ami" "bastion" {
  most_recent = true
  owners = ["self"]

  name_regex = "^${var.bastion_image_name_prefix}.*"
}

data "aws_ami" "cluster" {
  most_recent = true
  owners = ["self"]

  name_regex = "^${var.cluster_image_name_prefix}.*"
}
