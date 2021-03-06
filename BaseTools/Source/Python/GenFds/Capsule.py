## @file
# generate capsule
#
#  Copyright (c) 2007 - 2016, Intel Corporation. All rights reserved.<BR>
#
#  This program and the accompanying materials
#  are licensed and made available under the terms and conditions of the BSD License
#  which accompanies this distribution.  The full text of the license may be found at
#  http://opensource.org/licenses/bsd-license.php
#
#  THE PROGRAM IS DISTRIBUTED UNDER THE BSD LICENSE ON AN "AS IS" BASIS,
#  WITHOUT WARRANTIES OR REPRESENTATIONS OF ANY KIND, EITHER EXPRESS OR IMPLIED.
#

##
# Import Modules
#
from GenFdsGlobalVariable import GenFdsGlobalVariable
from CommonDataClass.FdfClass import CapsuleClassObject
import Common.LongFilePathOs as os
import subprocess
import StringIO
from Common.Misc import SaveFileOnChange
from GenFds import GenFds
from Common.Misc import PackRegistryFormatGuid
import uuid
from struct import pack
from GenFds import FindExtendTool
from Common import EdkLogger
from Common.BuildToolError import *


T_CHAR_LF = '\n'
WIN_CERT_REVISION      = 0x0200
WIN_CERT_TYPE_EFI_GUID = 0x0EF1
EFI_CERT_TYPE_PKCS7_GUID = uuid.UUID('{4aafd29d-68df-49ee-8aa9-347d375665a7}')
EFI_CERT_TYPE_RSA2048_SHA256_GUID = uuid.UUID('{a7717414-c616-4977-9420-844712a735bf}')

## create inf file describes what goes into capsule and call GenFv to generate capsule
#
#
class Capsule (CapsuleClassObject) :
    ## The constructor
    #
    #   @param  self        The object pointer
    #
    def __init__(self):
        CapsuleClassObject.__init__(self)
        # For GenFv
        self.BlockSize = None
        # For GenFv
        self.BlockNum = None
        self.CapsuleName = None

    ## Generate FMP capsule
    #
    #   @retval string      Generated Capsule file path
    #
    def GenFmpCapsule(self):
        #
        # Generate capsule header
        # typedef struct {
        #     EFI_GUID          CapsuleGuid;
        #     UINT32            HeaderSize;
        #     UINT32            Flags;
        #     UINT32            CapsuleImageSize;
        # } EFI_CAPSULE_HEADER;
        #
        Header = StringIO.StringIO()
        #
        # Use FMP capsule GUID: 6DCBD5ED-E82D-4C44-BDA1-7194199AD92A
        #
        Header.write(PackRegistryFormatGuid('6DCBD5ED-E82D-4C44-BDA1-7194199AD92A'))
        HdrSize = 0
        if 'CAPSULE_HEADER_SIZE' in self.TokensDict:
            Header.write(pack('=I', int(self.TokensDict['CAPSULE_HEADER_SIZE'], 16)))
            HdrSize = int(self.TokensDict['CAPSULE_HEADER_SIZE'], 16)
        else:
            Header.write(pack('=I', 0x20))
            HdrSize = 0x20
        Flags = 0
        if 'CAPSULE_FLAGS' in self.TokensDict:
            for flag in self.TokensDict['CAPSULE_FLAGS'].split(','):
                flag = flag.strip()
                if flag == 'PopulateSystemTable':
                    Flags |= 0x00010000 | 0x00020000
                elif flag == 'PersistAcrossReset':
                    Flags |= 0x00010000
                elif flag == 'InitiateReset':
                    Flags |= 0x00040000
        Header.write(pack('=I', Flags))
        #
        # typedef struct {
        #     UINT32 Version;
        #     UINT16 EmbeddedDriverCount;
        #     UINT16 PayloadItemCount;
        #     // UINT64 ItemOffsetList[];
        # } EFI_FIRMWARE_MANAGEMENT_CAPSULE_HEADER;
        #
        FwMgrHdr = StringIO.StringIO()
        if 'CAPSULE_HEADER_INIT_VERSION' in self.TokensDict:
            FwMgrHdr.write(pack('=I', int(self.TokensDict['CAPSULE_HEADER_INIT_VERSION'], 16)))
        else:
            FwMgrHdr.write(pack('=I', 0x00000001))
        FwMgrHdr.write(pack('=HH', len(self.CapsuleDataList), len(self.FmpPayloadList)))
        FwMgrHdrSize = 4+2+2+8*(len(self.CapsuleDataList)+len(self.FmpPayloadList))

        #
        # typedef struct _WIN_CERTIFICATE {
        #   UINT32 dwLength;
        #   UINT16 wRevision;
        #   UINT16 wCertificateType;
        # //UINT8 bCertificate[ANYSIZE_ARRAY];
        # } WIN_CERTIFICATE;
        #
        # typedef struct _WIN_CERTIFICATE_UEFI_GUID {
        #   WIN_CERTIFICATE Hdr;
        #   EFI_GUID        CertType;
        # //UINT8 CertData[ANYSIZE_ARRAY];
        # } WIN_CERTIFICATE_UEFI_GUID;
        #
        # typedef struct {
        #   UINT64                    MonotonicCount;
        #   WIN_CERTIFICATE_UEFI_GUID AuthInfo;
        # } EFI_FIRMWARE_IMAGE_AUTHENTICATION;
        #
        # typedef struct _EFI_CERT_BLOCK_RSA_2048_SHA256 {
        #   EFI_GUID HashType;
        #   UINT8 PublicKey[256];
        #   UINT8 Signature[256];
        # } EFI_CERT_BLOCK_RSA_2048_SHA256;
        #

        PreSize = FwMgrHdrSize
        Content = StringIO.StringIO()
        for driver in self.CapsuleDataList:
            FileName = driver.GenCapsuleSubItem()
            FwMgrHdr.write(pack('=Q', PreSize))
            PreSize += os.path.getsize(FileName)
            File = open(FileName, 'rb')
            Content.write(File.read())
            File.close()
        for fmp in self.FmpPayloadList:
            if fmp.Certificate_Guid:
                ExternalTool, ExternalOption = FindExtendTool([], GenFdsGlobalVariable.ArchList, fmp.Certificate_Guid)
                CmdOption = ''
                CapInputFile = fmp.ImageFile
                if not os.path.isabs(fmp.ImageFile):
                    CapInputFile = os.path.join(GenFdsGlobalVariable.WorkSpaceDir, fmp.ImageFile)
                CapOutputTmp = os.path.join(GenFdsGlobalVariable.FvDir, self.UiCapsuleName) + '.tmp'
                if ExternalTool == None:
                    EdkLogger.error("GenFds", GENFDS_ERROR, "No tool found with GUID %s" % fmp.Certificate_Guid)
                else:
                    CmdOption += ExternalTool
                if ExternalOption:
                    CmdOption = CmdOption + ' ' + ExternalOption
                CmdOption += ' -e ' + ' --monotonic-count ' + str(fmp.MonotonicCount) + ' -o ' + CapOutputTmp + ' ' + CapInputFile
                CmdList = CmdOption.split()
                GenFdsGlobalVariable.CallExternalTool(CmdList, "Failed to generate FMP auth capsule")
                if uuid.UUID(fmp.Certificate_Guid) == EFI_CERT_TYPE_PKCS7_GUID:
                    dwLength = 4 + 2 + 2 + 16 + os.path.getsize(CapOutputTmp) - os.path.getsize(CapInputFile)
                else:
                    dwLength = 4 + 2 + 2 + 16 + 16 + 256 + 256
                Buffer  = pack('Q', fmp.MonotonicCount)
                Buffer += pack('I', dwLength)
                Buffer += pack('H', WIN_CERT_REVISION)
                Buffer += pack('H', WIN_CERT_TYPE_EFI_GUID)
                Buffer += uuid.UUID(fmp.Certificate_Guid).get_bytes_le()
                if os.path.exists(CapOutputTmp):
                    TmpFile = open(CapOutputTmp, 'rb')
                    Buffer += TmpFile.read()
                    TmpFile.close()
                    if fmp.VendorCodeFile:
                        VendorFile = open(fmp.VendorCodeFile, 'rb')
                        Buffer += VendorFile.read()
                        VendorFile.close()
                    FwMgrHdr.write(pack('=Q', PreSize))
                    PreSize += len(Buffer)
                    Content.write(Buffer)
            else:
                payload = fmp.GenCapsuleSubItem()
                FwMgrHdr.write(pack('=Q', PreSize))
                PreSize += len(payload)
                Content.write(payload)
        BodySize = len(FwMgrHdr.getvalue()) + len(Content.getvalue())
        Header.write(pack('=I', HdrSize + BodySize))
        #
        # The real capsule header structure is 28 bytes
        #
        Header.write('\x00'*(HdrSize-28))
        Header.write(FwMgrHdr.getvalue())
        Header.write(Content.getvalue())
        #
        # Generate FMP capsule file
        #
        CapOutputFile = os.path.join(GenFdsGlobalVariable.FvDir, self.UiCapsuleName) + '.Cap'
        SaveFileOnChange(CapOutputFile, Header.getvalue(), True)
        return CapOutputFile

    ## Generate capsule
    #
    #   @param  self        The object pointer
    #   @retval string      Generated Capsule file path
    #
    def GenCapsule(self):
        if self.UiCapsuleName.upper() + 'cap' in GenFds.ImageBinDict.keys():
            return GenFds.ImageBinDict[self.UiCapsuleName.upper() + 'cap']

        GenFdsGlobalVariable.InfLogger( "\nGenerate %s Capsule" %self.UiCapsuleName)
        if ('CAPSULE_GUID' in self.TokensDict and 
            uuid.UUID(self.TokensDict['CAPSULE_GUID']) == uuid.UUID('6DCBD5ED-E82D-4C44-BDA1-7194199AD92A')):
            return self.GenFmpCapsule()

        CapInfFile = self.GenCapInf()
        CapInfFile.writelines("[files]" + T_CHAR_LF)
        CapFileList = []
        for CapsuleDataObj in self.CapsuleDataList :
            CapsuleDataObj.CapsuleName = self.CapsuleName
            FileName = CapsuleDataObj.GenCapsuleSubItem()
            CapsuleDataObj.CapsuleName = None
            CapFileList.append(FileName)
            CapInfFile.writelines("EFI_FILE_NAME = " + \
                                   FileName      + \
                                   T_CHAR_LF)
        SaveFileOnChange(self.CapInfFileName, CapInfFile.getvalue(), False)
        CapInfFile.close()
        #
        # Call GenFv tool to generate capsule
        #
        CapOutputFile = os.path.join(GenFdsGlobalVariable.FvDir, self.UiCapsuleName)
        CapOutputFile = CapOutputFile + '.Cap'
        GenFdsGlobalVariable.GenerateFirmwareVolume(
                                CapOutputFile,
                                [self.CapInfFileName],
                                Capsule=True,
                                FfsList=CapFileList
                                )

        GenFdsGlobalVariable.VerboseLogger( "\nGenerate %s Capsule Successfully" %self.UiCapsuleName)
        GenFdsGlobalVariable.SharpCounter = 0
        GenFds.ImageBinDict[self.UiCapsuleName.upper() + 'cap'] = CapOutputFile
        return CapOutputFile

    ## Generate inf file for capsule
    #
    #   @param  self        The object pointer
    #   @retval file        inf file object
    #
    def GenCapInf(self):
        self.CapInfFileName = os.path.join(GenFdsGlobalVariable.FvDir,
                                   self.UiCapsuleName +  "_Cap" + '.inf')
        CapInfFile = StringIO.StringIO() #open (self.CapInfFileName , 'w+')

        CapInfFile.writelines("[options]" + T_CHAR_LF)

        for Item in self.TokensDict.keys():
            CapInfFile.writelines("EFI_"                    + \
                                  Item                      + \
                                  ' = '                     + \
                                  self.TokensDict.get(Item) + \
                                  T_CHAR_LF)

        return CapInfFile
