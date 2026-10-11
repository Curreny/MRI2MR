function run_spm_segmentation(t1_file, spm_dir)
%RUN_SPM_SEGMENTATION Run SPM tissue segmentation for one T1 image.
% Input:
%   t1_file : full path to T1.nii
%   spm_dir  : SPM12 root directory
%
% Output:
%   c1T1.nii and c2T1.nii will be written beside T1.nii

    if isstring(t1_file)
        t1_file = char(t1_file);
    end
    if isstring(spm_dir)
        spm_dir = char(spm_dir);
    end

    if ~exist(t1_file, 'file')
        error('T1 file not found: %s', t1_file);
    end
    if ~exist(spm_dir, 'dir')
        error('SPM dir not found: %s', spm_dir);
    end

    addpath(spm_dir);
    spm('defaults', 'FMRI');
    spm_jobman('initcfg');

    [folder, name, ext] = fileparts(t1_file);
    if isempty(ext)
        t1_file = fullfile(folder, [name '.nii']);
    end

    tpm_file = fullfile(spm_dir, 'tpm', 'TPM.nii');

    matlabbatch = [];
    matlabbatch{1}.spm.spatial.preproc.channel.vols = {t1_file};
    matlabbatch{1}.spm.spatial.preproc.channel.biasreg = 0.001;
    matlabbatch{1}.spm.spatial.preproc.channel.biasfwhm = 60;
    matlabbatch{1}.spm.spatial.preproc.channel.write = [0 1];

    % Tissue 1: GM
    matlabbatch{1}.spm.spatial.preproc.tissue(1).tpm = {sprintf('%s,1', tpm_file)};
    matlabbatch{1}.spm.spatial.preproc.tissue(1).ngaus = 1;
    matlabbatch{1}.spm.spatial.preproc.tissue(1).native = [1 0];
    matlabbatch{1}.spm.spatial.preproc.tissue(1).warped = [0 0];

    % Tissue 2: WM
    matlabbatch{1}.spm.spatial.preproc.tissue(2).tpm = {sprintf('%s,2', tpm_file)};
    matlabbatch{1}.spm.spatial.preproc.tissue(2).ngaus = 1;
    matlabbatch{1}.spm.spatial.preproc.tissue(2).native = [1 0];
    matlabbatch{1}.spm.spatial.preproc.tissue(2).warped = [0 0];

    % Tissue 3: CSF
    matlabbatch{1}.spm.spatial.preproc.tissue(3).tpm = {sprintf('%s,3', tpm_file)};
    matlabbatch{1}.spm.spatial.preproc.tissue(3).ngaus = 2;
    matlabbatch{1}.spm.spatial.preproc.tissue(3).native = [0 0];
    matlabbatch{1}.spm.spatial.preproc.tissue(3).warped = [0 0];

    % Tissue 4: bone
    matlabbatch{1}.spm.spatial.preproc.tissue(4).tpm = {sprintf('%s,4', tpm_file)};
    matlabbatch{1}.spm.spatial.preproc.tissue(4).ngaus = 3;
    matlabbatch{1}.spm.spatial.preproc.tissue(4).native = [0 0];
    matlabbatch{1}.spm.spatial.preproc.tissue(4).warped = [0 0];

    % Tissue 5: soft tissue
    matlabbatch{1}.spm.spatial.preproc.tissue(5).tpm = {sprintf('%s,5', tpm_file)};
    matlabbatch{1}.spm.spatial.preproc.tissue(5).ngaus = 4;
    matlabbatch{1}.spm.spatial.preproc.tissue(5).native = [0 0];
    matlabbatch{1}.spm.spatial.preproc.tissue(5).warped = [0 0];

    % Tissue 6: air/background
    matlabbatch{1}.spm.spatial.preproc.tissue(6).tpm = {sprintf('%s,6', tpm_file)};
    matlabbatch{1}.spm.spatial.preproc.tissue(6).ngaus = 2;
    matlabbatch{1}.spm.spatial.preproc.tissue(6).native = [0 0];
    matlabbatch{1}.spm.spatial.preproc.tissue(6).warped = [0 0];

    matlabbatch{1}.spm.spatial.preproc.warp.mrf = 1;
    matlabbatch{1}.spm.spatial.preproc.warp.cleanup = 1;
    matlabbatch{1}.spm.spatial.preproc.warp.reg = [0 0.001 0.5 0.05 0.2];
    matlabbatch{1}.spm.spatial.preproc.warp.affreg = 'mni';
    matlabbatch{1}.spm.spatial.preproc.warp.fwhm = 0;
    matlabbatch{1}.spm.spatial.preproc.warp.samp = 3;
    matlabbatch{1}.spm.spatial.preproc.warp.write = [0 0];

    spm_jobman('run', matlabbatch);

    gm_file = fullfile(folder, ['c1' name ext]);
    wm_file = fullfile(folder, ['c2' name ext]);

    if ~exist(gm_file, 'file')
        error('GM output not found: %s', gm_file);
    end
    if ~exist(wm_file, 'file')
        error('WM output not found: %s', wm_file);
    end

    fprintf('SPM segmentation done.\n');
    fprintf('GM: %s\n', gm_file);
    fprintf('WM: %s\n', wm_file);
end