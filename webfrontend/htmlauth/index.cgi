#!/usr/bin/perl

# Copyright 2016-2019 Christian Woerstenfeld, git@loxberry.woerstenfeld.de
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#     http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


##########################################################################
# Modules
##########################################################################

use LoxBerry::Storage;
use LoxBerry::Web;
use LoxBerry::Log;
use CGI::Carp qw(fatalsToBrowser);
use CGI qw/:standard/;
use Config::Simple '-strict';
use HTML::Entities;
#use Cwd 'abs_path';
use warnings;
use strict;
no  strict "refs"; 

##########################################################################
# Variables
##########################################################################
my %Config;
my $logfile 					= "backuplog.log";
my $pluginconfigfile 			= "miniserverbackup.cfg";
my $languagefile				= "language.ini";
my $maintemplatefilename 		= "settings.html";
my $helptemplatefilename		= "help.html";
my $errortemplatefilename 		= "error.html";
my $successtemplatefilename 	= "success.html";
my $backupstate_name 			= "backupstate.txt";
my $backupstate_file 			= $lbphtmldir."/".$backupstate_name;
my $backupstate_tmp_file 		= "/tmp/".$backupstate_name;
my @netshares 					= LoxBerry::Storage::get_netshares();
my @usbdevices 					= LoxBerry::Storage::get_usbstorage();
my $localstorage                = $lbpdatadir."/files";
my %backup_interval_minutes		= (0,30,60,240,1440,10080,43200,-1);
my %backups_to_keep_values		= (1,3,7,14,30,60,90,365);
my %file_formats				= ('7z','zip','uncompressed');
my $finalstorage;
my $error_message				= "";
my $no_error_template_message	= "<b>Miniserver-Backup:</b> The error template is not readable. We must abort here. Please try to reinstall the plugin.";
my @pluginconfig_bletags;
my $template_title;
my $helpurl 					= "http://www.loxwiki.eu/display/LOXBERRY/Miniserverbackup";
my @tagrow;
my @tag;
my @tag_cfg_data;
my @msrow;
my @ms;
my $log 						= LoxBerry::Log->new ( name => 'Miniserverbackup', filename => $lbplogdir ."/". $logfile, append => 1 );
my $do="form";
our $tag_id;
our $ms_id;
our @config_params;
our @language_strings;

##########################################################################
# Read Settings
##########################################################################

# Version 
my $version = LoxBerry::System::pluginversion();
my $plugin = LoxBerry::System::plugindata();
$LoxBerry::System::DEBUG 	= 1 if $plugin->{PLUGINDB_LOGLEVEL} eq 7;
$LoxBerry::Web::DEBUG 		= 1 if $plugin->{PLUGINDB_LOGLEVEL} eq 7;
$log->loglevel($plugin->{PLUGINDB_LOGLEVEL});
LOGSTART "Version: ".$version   if $plugin->{PLUGINDB_LOGLEVEL} eq 7;
LOGDEB   "Init CGI and import names in namespace R::";
my $cgi 	= CGI->new;
$cgi->import_names('R');

if ( $plugin->{PLUGINDB_LOGLEVEL} eq 7 )
{
	no strict 'subs';
	foreach (sort keys %R::) 
	{
		LOGDEB "Variable => R::$_ = " . eval '$'. R . "::$_"  ;
	}
	use strict "subs";
}

# Prevent errors in Apache error log
$R::delete_log if (0);
$R::do if (0);

my $lang = lblanguage();
LOGDEB   "Language is: " . $lang;

stat($lbptemplatedir . "/" . $errortemplatefilename);
if ( !-r _ )
{
	$error_message = $no_error_template_message;
	LoxBerry::Web::lbheader($template_title, $helpurl, $helptemplatefilename);
	print $error_message;
	LOGCRIT $error_message;
	LoxBerry::Web::lbfooter();
	LOGDEB "Leaving Plugin due to an unrecoverable error";
	exit;
}

my $errortemplate = HTML::Template->new(
		filename => $lbptemplatedir . "/" . $errortemplatefilename,
		global_vars => 1,
		loop_context_vars => 1,
		die_on_bad_params=> 0,
		associate => $cgi,
		%htmltemplate_options,
		debug => 1,
		);
my %ERR = LoxBerry::System::readlanguage($errortemplate, $languagefile);

#Prevent blocking / Recreate state file if missing or older than 120 * 60 sec = 2 hrs)
$error_message = $ERR{'ERRORS.ERR_0029_PROBLEM_WITH_STATE_FILE'};
if ( -f $backupstate_tmp_file )
{
	if ((time - (stat $backupstate_tmp_file)[9]) > (120 * 60)) 
	{
	  	my $filename = $backupstate_tmp_file;
		open(my $fh, '>', $filename) or &error;
		print $fh "-";
		close $fh;
	}
}
else
{
  	my $filename = $backupstate_tmp_file;
	open(my $fh, '>', $filename) or &error;
	print $fh "-";
	close $fh;
}
if (! -l $backupstate_file)
{
	if ( -f $backupstate_file)
	{
		unlink($backupstate_file) or &error;
	}
	symlink($backupstate_tmp_file, $backupstate_file) or &error;
}

stat($lbpconfigdir . "/" . $pluginconfigfile);
if (!-r _ || -z _ ) 
{
	$error_message = $ERR{'ERRORS.ERR_0030_ERROR_CREATE_CONFIG_DIRECTORY'};
	mkdir $lbpconfigdir unless -d $lbpconfigdir or &error; 
	$error_message = $ERR{'ERRORS.ERR_0031_ERROR_CREATE_CONFIG_FILE'};
	open my $configfileHandle, ">", $lbpconfigdir . "/" . $pluginconfigfile or &error;
		print $configfileHandle "[MSBACKUP]\n";
		print $configfileHandle "VERSION=$version\n";
	close $configfileHandle;
	$error_message = $ERR{'MINISERVERBACKUP.INF_0070_CREATE_CONFIG_OK'};
	&error; 
}

if ( $R::delete_log )
{
	$log->close;
	$error_message = $ERR{'ERRORS.ERR_0032_ERROR_DELETE_LOGFILE'};
	open(my $fh, '>', $lbplogdir ."/". $logfile) or &error;
	print $fh "";
	close $fh;
	$log->open;
	LOGOK $ERR{'MINISERVERBACKUP.INF_0069_DELETE_LOGFILE'}. " " .$lbplogdir ."/". $logfile;
	LOGSTART "Version: ".$version;
	print "Content-Type: text/plain\n\nOK";
	exit;
}

# Get plugin config
my $plugin_cfg 		= new Config::Simple($lbpconfigdir . "/" . $pluginconfigfile);
$plugin_cfg 		= Config::Simple->import_from($lbpconfigdir . "/" . $pluginconfigfile,  \%Config);
$error_message      = $ERR{'ERRORS.ERR_0028_ERROR_READING_CFG'}. "<br>" . Config::Simple->error();
&error if (! %Config);

# Get through all the config options
LOGDEB "Plugin config read.";
if ( $plugin->{PLUGINDB_LOGLEVEL} eq 7 )
{
	foreach (sort keys %Config) 
	{ 
		LOGDEB "Plugin config line => ".$_."=".$Config{$_}; 
	} 
}
my %miniservers;
%miniservers = LoxBerry::System::get_miniservers();
$error_message = $ERR{'ERRORS.ERR_0033_MS_CONFIG_NO_IP'}."<br>".$ERR{'ERRORS.ERR_0034_MS_CONFIG_NO_IP_SUGGESTION'};  
&error if (! %miniservers);
&error if (  $miniservers{1}{IPAddress} eq "" );
LOGDEB "Miniserver config read.";
if ( $plugin->{PLUGINDB_LOGLEVEL} eq 7 )
{
	foreach (sort keys %miniservers) 
	{ 
		 LOGDEB "Miniserver #$_ Name => ".$miniservers{$_}{'Name'};
		 LOGDEB "Miniserver #$_ IP   => ".$miniservers{$_}{'IPAddress'};
	} 
}

my $maintemplate = HTML::Template->new(
		filename => $lbptemplatedir . "/" . $maintemplatefilename,
		global_vars => 1,
		loop_context_vars => 1,
		die_on_bad_params=> 0,
		%htmltemplate_options,
		debug => 1
		);
my %L = LoxBerry::System::readlanguage($maintemplate, $languagefile);
$maintemplate->param( "LBPPLUGINDIR", $lbpplugindir);
$maintemplate->param( "MINISERVERS"	, int( keys(%miniservers)) );
$maintemplate->param( "LOGO_ICON"	, get_plugin_icon(64) );
$maintemplate->param( "VERSION"		, $version);
$maintemplate->param( "LOGLEVEL" 	, $L{"LOGGING.LOGLEVEL".$plugin->{PLUGINDB_LOGLEVEL}});
$maintemplate->param( "ELFINDER_LANG"		, $lang);

my $index = 0;
$index++ while $netshares[$index]->{NETSHARE_STATE} eq 'Writable' ;
splice(@netshares, $index, 1);

$maintemplate->param('HTTP_SERVER','http://'.$ENV{HTTP_HOST});
$maintemplate->param('HTTP_SERVER','https://'.$ENV{HTTP_HOST}) if ( $ENV{HTTPS} eq 'on' );


$lbplogdir =~ s/$lbhomedir\/log\///; # Workaround due to missing variable for Logview

LOGDEB "Check for pending notifications for: " . $lbpplugindir . " " . $L{'GENERAL.MY_NAME'};
my $notifications = LoxBerry::Log::get_notifications_html($lbpplugindir, $L{'GENERAL.MY_NAME'});
LOGDEB "Notifications are:\n".encode_entities($notifications) if $notifications;
LOGDEB "No notifications pending." if !$notifications;
$maintemplate->param( "NOTIFICATIONS" , $notifications);

$maintemplate->param( "LOGFILE" 	, $lbplogdir ."/". $logfile);
	
LOGDEB "Check, if filename for the successtemplate is readable";
stat($lbptemplatedir . "/" . $successtemplatefilename);
if ( !-r _ )
{
	LOGDEB "Filename for the successtemplate is not readable, that's bad";
	$error_message = $ERR{'ERRORS.ERR_SUCCESS_TEMPLATE_NOT_READABLE'};
	&error;
}
LOGDEB "Filename for the successtemplate is ok, preparing template";
my $successtemplate = HTML::Template->new(
		filename => $lbptemplatedir . "/" . $successtemplatefilename,
		global_vars => 1,
		loop_context_vars => 1,
		die_on_bad_params=> 0,
		associate => $cgi,
		%htmltemplate_options,
		debug => 1,
		);
LOGDEB "Read success strings from " . $languagefile . " for language " . $lang;
my %SUC = LoxBerry::System::readlanguage($successtemplate, $languagefile);

##########################################################################
# Main program
##########################################################################

$R::do if 0; # Prevent errors


LOGDEB "Is it a start backup call?";
if ( $R::do eq "backup") 
{
	  &backup;
}

LOGDEB "Call default page";
&form;
exit;

#####################################################
# 
# Subroutines
#
#####################################################

#####################################################
# Form-Sub
#####################################################

	sub form 
	{
		# The page title read from language file + our name
		$template_title = $L{"GENERAL.MY_NAME"};

		# Print Template header
		LoxBerry::Web::lbheader($template_title, $helpurl, $helptemplatefilename);

	my @template_row;
	foreach my $ms_id (  sort keys  %miniservers) 
	{ 
	my @row;
	my %row;
		 LOGDEB "Miniserver $ms_id Name => ".$miniservers{$ms_id}{'Name'};
		 LOGDEB "Miniserver $ms_id IP   => ".$miniservers{$ms_id}{'IPAddress'};
		
		my %ms;
		$ms{Name} 			= $miniservers{$ms_id}{'Name'};
		$ms{IPAddress} 		= $miniservers{$ms_id}{'IPAddress'};

		my $nsc=0;
		my @netshares_converted;
		my @netshares_plus_subfolder;
		foreach my $netshare (@netshares) 
		{
  			$netshares_plus_subfolder[$nsc]{NETSHARE_SHARENAME} = $netshare->{NETSHARE_SHARENAME};
  			$netshares_plus_subfolder[$nsc]{NETSHARE_SUBFOLDER} = " ".$L{"GENERAL.BACKUP_SUBFOLDER_DROPDOWN_TEXT"};
  			$netshares_plus_subfolder[$nsc]{NETSHARE_SERVER} 	= $netshare->{NETSHARE_SERVER};
  			$netshares_plus_subfolder[$nsc]{NETSHARE_SHAREPATH} = $netshare->{NETSHARE_SHAREPATH}."+";
    		$nsc++;
		}
		push(@netshares_converted, @netshares);
		push(@netshares_converted, @netshares_plus_subfolder);

		my $udc=0;
		my @usbdevices_converted;
		my @usbdevices_plus_subfolder;
		foreach my $usbdevice (@usbdevices) 
		{
  			$usbdevices_plus_subfolder[$udc]{USBSTORAGE_DEVICE} 	= $usbdevice->{USBSTORAGE_DEVICE};
  			$usbdevices_plus_subfolder[$udc]{USBSTORAGE_SUBFOLDER} 	= " ".$L{"GENERAL.BACKUP_SUBFOLDER_DROPDOWN_TEXT"};
  			$usbdevices_plus_subfolder[$udc]{USBSTORAGE_NO} 	 	= $usbdevice->{USBSTORAGE_NO};
  			$usbdevices_plus_subfolder[$udc]{USBSTORAGE_DEVICEPATH} = $usbdevice->{USBSTORAGE_DEVICEPATH}."+";
    		$udc++;
		}
		push(@usbdevices_converted, @usbdevices);
		push(@usbdevices_converted, @usbdevices_plus_subfolder);

		push @{ $row{'MSROW'} }					, \%ms;
		        $row{'MSID'} 					= $ms_id;
				$row{'NETSHARES'} 				= \@netshares_converted;
				$row{'USBDEVICES'} 				= \@usbdevices_converted;
				$row{'LOCALSTORAGE'} 			= $localstorage;
				$row{'CURRENT_STORAGE'}			= $localstorage;
				$row{'CURRENT_INTERVAL'}		= 0;
				$row{'CURRENT_FILE_FORMAT'}		= "zip";
				$row{'CURRENT_BACKUPS_TO_KEEP'}	= "7";
				$row{'CURRENT_STORAGE'}			= $Config{"MINISERVERBACKUP.FINALSTORAGE".$ms_id} if ( $Config{"MINISERVERBACKUP.FINALSTORAGE".$ms_id} ne "" );
				$row{'CURRENT_INTERVAL'}		= $Config{"MINISERVERBACKUP.BACKUP_INTERVAL".$ms_id} if ( $Config{"MINISERVERBACKUP.BACKUP_INTERVAL".$ms_id} ne "" );
				$row{'CURRENT_FILE_FORMAT'}		= $Config{"MINISERVERBACKUP.FILE_FORMAT".$ms_id} if ( $Config{"MINISERVERBACKUP.FILE_FORMAT".$ms_id} ne "" );
				$row{'CURRENT_BACKUPS_TO_KEEP'}	= $Config{"MINISERVERBACKUP.BACKUPS_TO_KEEP".$ms_id} if ( $Config{"MINISERVERBACKUP.BACKUPS_TO_KEEP".$ms_id} ne "" );
				$row{'AUTOSAVE_CONFIG'}	    	= 1 if ( $Config{"MINISERVERBACKUP.FINALSTORAGE".$ms_id} eq "" || $Config{"MINISERVERBACKUP.BACKUP_INTERVAL".$ms_id} eq "" || $Config{"MINISERVERBACKUP.FILE_FORMAT".$ms_id} eq "" || $Config{"MINISERVERBACKUP.BACKUPS_TO_KEEP".$ms_id} eq "" );
				
				my $backup_intervals;
				foreach  (  sort { $a <=> $b } %backup_interval_minutes) 
				{ 
					$backup_intervals = $backup_intervals . '<OPTION value="'.$_.'"> '.$L{"MINISERVERBACKUP.INTERVAL".$_}.' </OPTION>' if ( $_ ne "" );
					LOGDEB "->".$_ if ( $_ ne "" );
				}
				$row{'BACKUP_INTERVAL_VALUE'} 	= $backup_intervals;

				my $file_formats;
				foreach  (  sort { $a <=> $b } %file_formats) 
				{ 
					$file_formats = $file_formats . '<OPTION value="'.$_.'"> '.$L{"MINISERVERBACKUP.FILE_FORMAT_" . uc $_ }.' </OPTION>' if ( $_ ne "" );
					LOGDEB "->".$_ if ( $_ ne "" );
				}
				$row{'BACKUP_FILE_FORMAT'} 	= $file_formats;

				my $backups_to_keep;
				foreach  (  sort { $a <=> $b } %backups_to_keep_values) 
				{ 
					$backups_to_keep = $backups_to_keep . '<OPTION value="'.$_.'"> '.$_.' </OPTION>' if ( $_ ne "" );
					LOGDEB "->".$_ if ( $_ ne "" );
				}
				$row{'BACKUPS_TO_KEEP_VALUE'} 	= $backups_to_keep;

		push(@template_row, \%row);
		
	}	
	

	$maintemplate->param("TEMPLATE_ROW" => \@template_row);
	
#	exit;



    # Parse some strings from language file into template 
		our $str_tags    	  	= $L{"default.TXT_BLUETOOTH_TAGS"};
	
		
		# Parse page

		# Parse page footer		
		#$maintemplate->param("TAGROW" => \@tagrow);
		$maintemplate->param("HTMLPATH" => "/plugins/".$lbpplugindir."/");
		$maintemplate->param("BACKUPSTATEFILE" => $backupstate_name);
	
    	print $maintemplate->output();
		LoxBerry::Web::lbfooter();
		exit;
	}

#####################################################
# Error-Sub
#####################################################
sub error 
{
	LOGDEB "Sub error";
	LOGERR 	"[".localtime()."] ".$error_message;
	LOGDEB "Set page title, load header, parse variables, set footer, end with error";
	$template_title = $ERR{'ERRORS.MY_NAME'} . " - " . $ERR{'ERRORS.ERR_TITLE'};
	LoxBerry::Web::lbheader($template_title, $helpurl, $helptemplatefilename);
	$errortemplate->param('ERR_MESSAGE'		, $error_message);
	$errortemplate->param('ERR_TITLE'		, $ERR{'ERRORS.ERR_TITLE'});
	$errortemplate->param('ERR_BUTTON_BACK' , $ERR{'ERRORS.ERR_BUTTON_BACK'});
	print $errortemplate->output();
	LoxBerry::Web::lbfooter();
	LOGDEB "Leaving Miniserverbackup Plugin with an error";
	exit;
}


######################################################
## Manual backup-Sub
######################################################
#
	sub backup 
	{
		print "Content-Type: text/plain\n\n";
		# Create Backup
		# Without the following workaround
		# the script cannot be executed as
		# background process via CGI
		my $pid = fork();
		die "Fork failed: $!" if !defined $pid;
		if ($pid == 0) 
		{
			 # do this in the child
			 open STDIN, "</dev/null";
			 open STDOUT, ">/dev/null";
			 open STDERR, ">/dev/null";
			 LOGDEB "call $lbcgidir/bin/createmsbackup.pl manual";
			 system("$lbcgidir/bin/createmsbackup.pl manual &");
		}
		print ($L{"GENERAL.MY_NAME"}." OK");
		exit;
	}